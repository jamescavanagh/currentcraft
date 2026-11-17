"""Handoff routing between plates. Candidates come from simulated crossings; only gate decisions resolve them."""

from __future__ import annotations

from typing import Iterable

from app.application.process.contracts import ProcessExecution

from .contracts import EventEnvelope, Route, make_event
from .ports import MessageBrokerPort


class HandoffError(ValueError):
    """A gate decision cannot resolve the candidate."""


class HandoffRouter:
    """Turns plate crossings into at most one pending candidate per (object, route); resolves them via decide()."""

    def __init__(self, broker: MessageBrokerPort, routes: Iterable[Route]):
        self.broker = broker
        self.routes = tuple(routes)
        self._pending: dict[str, EventEnvelope] = {}
        self._open: set[tuple[str, str, str]] = set()
        self.subscription = broker.subscribe("plate/+/crossing", self._on_crossing)

    def _on_crossing(self, event: EventEnvelope) -> None:
        plate, obj, direction = event.payload.get("plate_id"), event.payload.get("object_id"), event.payload.get("direction")
        if not obj:
            return
        for r in self.routes:
            if r.from_plate != plate or (r.direction and r.direction != direction):
                continue
            key = (str(obj), r.from_plate, r.to_plate)
            if key in self._open:
                continue  # one pending candidate per object and route; later crossings are not stacked
            cand = make_event(topic=f"plate/{r.to_plate}/intake", kind="object.handoff", source="handoff-router",
                              epistemic_status="simulated", sim_time=event.sim_time,
                              correlation_id=event.correlation_id, causation_id=event.event_id,
                              payload={"object_id": obj, "from_plate": r.from_plate, "to_plate": r.to_plate,
                                       "direction": direction, "status": "candidate"})
            self._open.add(key)
            self._pending[cand.event_id] = cand
            self.broker.publish(cand)

    def pending(self) -> tuple[EventEnvelope, ...]:
        return tuple(self._pending.values())

    def decide(self, candidate_event_id: str, execution: ProcessExecution) -> EventEnvelope:
        """Resolve a candidate with a human gate execution. Release rules are enforced by ProcessExecution itself."""
        cand = self._pending.get(candidate_event_id)
        if cand is None:
            raise HandoffError("unknown or already resolved candidate")
        if execution.decision is None:
            raise HandoffError("execution carries no decision")
        obj = cand.payload["object_id"]
        if not any(i.object_id == obj and i.effect in ("checks", "transfers") for i in execution.incidence):
            raise HandoffError(f"execution must check or transfer {obj!r}")
        if execution.epistemic_status != "computed" or execution.occurred_at is None:
            raise HandoffError("decisions must be computed records with a real timestamp")
        decision = make_event(topic=f"gate/{execution.execution_id}/decision", kind="gate.decision",
                              source=execution.execution_id, epistemic_status="computed",
                              occurred_at=execution.occurred_at, correlation_id=cand.correlation_id,
                              causation_id=cand.event_id,
                              payload={"object_id": obj, "from_plate": cand.payload["from_plate"],
                                       "to_plate": cand.payload["to_plate"], "decision": execution.decision,
                                       "authority_role": execution.authority.holder_role if execution.authority else None,
                                       "evidence": ",".join(execution.verification_evidence) or None})
        self.broker.publish(decision)
        del self._pending[candidate_event_id]
        self._open.discard((str(obj), str(cand.payload["from_plate"]), str(cand.payload["to_plate"])))
        return decision
