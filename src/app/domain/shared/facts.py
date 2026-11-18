"""Evidenced facts, explicit unknowns and time windows; no I/O."""
from datetime import datetime
from typing import Generic, TypeVar
from pydantic import BaseModel, ConfigDict, model_validator
from .identity import EvidenceId, Text

T = TypeVar("T")


class Fact(BaseModel, Generic[T]):
    """A typed source assertion; missing does not mean zero, false or empty."""
    model_config = ConfigDict(frozen=True, extra="forbid", validate_default=True,
        json_schema_extra={"allOf": [{"if": {"properties": {"value": {"type": "null"}},
            "required": ["value"]}, "then": {"required": ["missing_reason"],
            "properties": {"missing_reason": {"type": "string", "minLength": 1}}},
            "else": {"required": ["evidence_ids"],
            "properties": {"evidence_ids": {"minItems": 1}, "missing_reason": {"type": "null"}}}}]})
    value: T | None
    missing_reason: Text | None = None
    evidence_ids: tuple[EvidenceId, ...] = ()

    @model_validator(mode="after")
    def check_fact(self):
        if self.value is None:
            if self.missing_reason is None:
                raise ValueError("missing value requires missing_reason")
        elif self.missing_reason is not None or not self.evidence_ids:
            raise ValueError("known value requires evidence and no missing_reason")
        if len(set(self.evidence_ids)) != len(self.evidence_ids):
            raise ValueError("duplicate evidence IDs")
        return self


def unknown() -> dict:
    """Input for a typed Fact default, validated by its owning model."""
    return {"value": None, "missing_reason": "not supplied"}


class TimeWindow(BaseModel):
    """Half-open timezone-aware interval; seconds are not inferred from dates."""
    model_config = ConfigDict(frozen=True, extra="forbid")
    start: datetime
    end: datetime

    @model_validator(mode="after")
    def check_window(self):
        if any(d.tzinfo is None or d.utcoffset() is None for d in (self.start, self.end)):
            raise ValueError("timestamps must be timezone-aware")
        if self.end <= self.start:
            raise ValueError("end must be after start")
        return self
