"""Evidenced facts, explicit unknowns and time windows; no I/O."""
from datetime import date, datetime
from typing import Generic, Literal, TypeVar
from pydantic import BaseModel, ConfigDict, Field, model_validator
from .identity import EvidenceId, Text

T = TypeVar("T")


class Fact(BaseModel, Generic[T]):
    """A typed source assertion; missing does not mean zero, false or empty."""
    model_config = ConfigDict(frozen=True, extra="forbid", validate_default=True)
    value: T | None
    epistemic_status: Literal["observed", "inferred", "unknown"]
    missing_reason: Text | None = None
    evidence_ids: tuple[EvidenceId, ...] = ()

    @model_validator(mode="after")
    def check_fact(self):
        if self.value is None:
            if self.missing_reason is None or self.epistemic_status != "unknown":
                raise ValueError("missing value requires unknown status and missing_reason")
        elif self.missing_reason is not None or not self.evidence_ids or self.epistemic_status == "unknown":
            raise ValueError("known value requires observed/inferred status, evidence and no missing_reason")
        if len(set(self.evidence_ids)) != len(self.evidence_ids):
            raise ValueError("duplicate evidence IDs")
        return self

    @classmethod
    def __get_pydantic_json_schema__(cls, core_schema, handler):
        schema = handler.resolve_ref_schema(handler(core_schema))
        schema.setdefault("allOf", []).append({"oneOf": [
            {"required": ["value", "epistemic_status", "missing_reason"],
             "properties": {"value": {"type": "null"}, "epistemic_status": {"const": "unknown"},
                            "missing_reason": {"type": "string", "minLength": 1, "pattern": r"\S"}}},
            {"required": ["value", "epistemic_status", "evidence_ids"],
             "properties": {"value": {"not": {"type": "null"}},
                            "epistemic_status": {"enum": ["observed", "inferred"]},
                            "evidence_ids": {"minItems": 1}, "missing_reason": {"type": "null"}}}
        ]})
        schema["properties"]["evidence_ids"]["uniqueItems"] = True
        return schema


def unknown() -> dict:
    """Input for a typed Fact default, validated by its owning model."""
    return {"value": None, "epistemic_status": "unknown", "missing_reason": "not supplied"}


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


class DateBounds(BaseModel):
    """Proposed agreement-date encoding; either bound can be explicitly unknown."""
    model_config = ConfigDict(frozen=True, extra="forbid", validate_default=True)
    starts_on: Fact[date] = Field(default_factory=unknown)
    ends_on: Fact[date] = Field(default_factory=unknown)

    @model_validator(mode="after")
    def ordered_known_bounds(self):
        if self.starts_on.value is not None and self.ends_on.value is not None:
            if self.ends_on.value < self.starts_on.value:
                raise ValueError("known agreement end precedes start")
        return self
