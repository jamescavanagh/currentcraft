"""Probe use cases and the label book."""

from __future__ import annotations

from typing import Optional

from app.application.messaging.contracts import make_event
from app.application.messaging.ports import MessageBrokerPort
from app.application.simulation.ports import TensorStorePort
from app.application.simulation.tensors import TensorContractError

from .contracts import CandidateRequest, CandidateSet, LabelEvent, LensReading, LensRequest, ProbeCloud, ProbeReading, ProbeRequest
from .ports import CandidatePort, LensPort, ProbePort


class ProbeService:
    def __init__(self, store: TensorStorePort, probe: ProbePort, lens: LensPort, candidates: CandidatePort):
        self.store, self._probe, self._lens, self._candidates = store, probe, lens, candidates

    def _check(self, request: ProbeRequest):
        if not self.store.contains(request.cloud.positions):
            raise TensorContractError("cloud positions not in shared store")

    def measure(self, request: ProbeRequest) -> ProbeReading:
        self._check(request)
        r = self._probe.measure(request)
        if r.request_digest != request.digest() or not self.store.contains(r.slab_coords):
            raise TensorContractError("probe provenance mismatch")
        return r

    def lens(self, request: LensRequest) -> LensReading:
        self._check(request.probe)
        return self._lens.lens(request)

    def candidates(self, request: CandidateRequest) -> CandidateSet:
        self._check(request.probe)
        return self._candidates.cluster(request)


class LabelError(ValueError):
    """A label event cannot be recorded."""


class LabelBook:
    """Records human label events against one cloud, publishes them, and reports conflicts."""

    def __init__(self, cloud: ProbeCloud, broker: Optional[MessageBrokerPort] = None):
        self.cloud, self.broker = cloud, broker
        self._ids = set(cloud.ids)
        self.events: list[LabelEvent] = []

    def record(self, event: LabelEvent):
        unknown = sorted(set(event.target_ids) - self._ids)
        if unknown:
            raise LabelError(f"unknown target ids: {unknown[:5]}")
        self.events.append(event)
        if self.broker is None:
            return None
        env = make_event(topic=f"hil/label/{event.target_kind}", kind="hil.label", source=self.cloud.cloud_id,
                         epistemic_status="computed", occurred_at=event.occurred_at, correlation_id=event.candidate_ref,
                         payload={"cloud_id": self.cloud.cloud_id, "target_kind": event.target_kind,
                                  "target_ids": ",".join(event.target_ids), "label": event.label,
                                  "labeler_role": event.labeler_role, "blind": event.blind,
                                  "reading_digest": event.reading_digest, "candidate_ref": event.candidate_ref})
        self.broker.publish(env)
        return env

    def labels_by_record(self) -> dict[str, tuple[str, ...]]:
        out: dict[str, set[str]] = {}
        for e in self.events:
            for i in e.target_ids:
                out.setdefault(i, set()).add(e.label)
        return {k: tuple(sorted(v)) for k, v in sorted(out.items())}

    def conflicts(self) -> dict[str, tuple[str, ...]]:
        """Records that carry more than one distinct label."""
        return {k: v for k, v in self.labels_by_record().items() if len(v) > 1}
