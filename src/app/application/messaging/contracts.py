"""Event envelope and routing contracts. Pydantic only; design source docs/architecture/MESSAGE_BROKER.md."""

from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime
from typing import Annotated, Literal, Optional, Union

from pydantic import Field, StringConstraints, model_validator

from app.application.common.contracts import _Frozen

SCHEMA_VERSION = "datamesh-event/v1"
LEVEL = r"[A-Za-z0-9._:-]+"
TOPIC_RE = re.compile(rf"^{LEVEL}(/{LEVEL}){{0,7}}$")
PATTERN_RE = re.compile(rf"^({LEVEL}|\+)(/({LEVEL}|\+)){{0,7}}(/#)?$|^#$")

Ident = Annotated[str, StringConstraints(pattern=r"^[A-Za-z0-9._:-]{1,120}$")]
Topic = Annotated[str, StringConstraints(pattern=TOPIC_RE.pattern, max_length=300)]
Scalar = Union[str, int, float, bool, None]
EventKind = Literal["plate.run", "plate.crossing", "object.handoff", "gate.decision", "object.lifecycle", "iot.reading", "hil.label", "raw.item", "domain.object", "domain.stored", "ingest.rejection"]
EpistemicStatus = Literal["computed", "simulated", "unknown"]


def valid_pattern(pattern: str) -> bool:
    """MQTT-style subscribe pattern: '+' matches one level, a final '#' matches the rest.

    >>> valid_pattern("plate/+/crossing"), valid_pattern("plate/#"), valid_pattern("plate/#/x")
    (True, True, False)
    """
    return bool(PATTERN_RE.match(pattern))


def topic_matches(pattern: str, topic: str) -> bool:
    """MQTT matching. '#' also matches the parent level.

    >>> topic_matches("plate/+/crossing", "plate/a/crossing"), topic_matches("plate/#", "plate"), topic_matches("plate/+", "plate/a/b")
    (True, True, False)
    """
    p, t = pattern.split("/"), topic.split("/")
    for i, level in enumerate(p):
        if level == "#":
            return True
        if i >= len(t) or (level != "+" and level != t[i]):
            return False
    return len(p) == len(t)


class EventEnvelope(_Frozen):
    """One broker message. Payload is flat scalars; tensors travel as store key and SHA-256 only."""

    schema_version: Literal["datamesh-event/v1"] = Field(default=SCHEMA_VERSION, description="Envelope version.")
    event_id: Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{64}$")] = Field(description="Content hash from make_event; duplicates are dropped.")
    topic: Topic = Field(description="'/'-separated levels, no wildcards.")
    kind: EventKind = Field(description="Event type.")
    source: Ident = Field(description="Producer, e.g. a plate id, router or device id.")
    epistemic_status: EpistemicStatus = Field(description="computed needs occurred_at; simulated needs sim_time.")
    sim_time: Optional[float] = Field(default=None, allow_inf_nan=False, description="Model time, for simulated events.")
    occurred_at: Optional[datetime] = Field(default=None, description="Real timestamp, for computed events.")
    correlation_id: Optional[Ident] = Field(default=None, description="Chain id shared by related events.")
    causation_id: Optional[Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{64}$")]] = Field(default=None, description="event_id of the event that caused this one.")
    payload: dict[str, Scalar] = Field(default_factory=dict, description="Flat JSON scalars only.")

    @model_validator(mode="after")
    def _rules(self):
        if self.epistemic_status == "computed" and self.occurred_at is None:
            raise ValueError("computed events need a real occurred_at timestamp")
        if self.epistemic_status == "simulated" and self.sim_time is None:
            raise ValueError("simulated events need sim_time")
        if len(self.payload) > 64 or any(len(k) > 60 for k in self.payload):
            raise ValueError("payload too large: keep it flat and small, reference tensors by key")
        if self.event_id != _digest({k: getattr(self, k) for k in _HASHED}):
            raise ValueError("event_id must be the content hash; build envelopes with make_event")
        return self


_HASHED = ("topic", "kind", "source", "epistemic_status", "sim_time", "occurred_at", "correlation_id", "causation_id", "payload")


def _digest(fields: dict) -> str:
    body = {k: fields.get(k) for k in _HASHED}
    body["occurred_at"] = body["occurred_at"].isoformat() if body["occurred_at"] else None
    return hashlib.sha256(json.dumps(body, sort_keys=True, default=str).encode()).hexdigest()


def make_event(*, topic: str, kind: str, source: str, epistemic_status: str, payload=None, sim_time=None,
               occurred_at=None, correlation_id=None, causation_id=None) -> EventEnvelope:
    """Build an envelope whose event_id is its content hash, so re-publishing is idempotent."""
    fields = dict(topic=topic, kind=kind, source=source, epistemic_status=epistemic_status, payload=dict(payload or {}),
                  sim_time=sim_time, occurred_at=occurred_at, correlation_id=correlation_id, causation_id=causation_id)
    return EventEnvelope(event_id=_digest(fields), **fields)


class Route(_Frozen):
    """Where crossings on one plate become candidate handoffs to another."""

    from_plate: Ident = Field(description="Plate whose crossings are routed.")
    to_plate: Ident = Field(description="Plate whose intake receives the candidate.")
    direction: Literal[-1, 0, 1] = Field(default=0, description="Crossing direction routed: +1 to the + side, -1 to the - side, 0 any.")


CONTRACTS = (EventEnvelope, Route)
