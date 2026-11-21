"""P4 suspicion, investigation, confirmation, closure and reopening history."""
from datetime import datetime
from typing import ClassVar, Literal
from pydantic import model_validator
from app.domain.shared.versioning import Label, P4Record, VersionRef, aware, unique


class Nonconformity(P4Record):
    """Versioned finding; correction and verification are separate records."""
    SOURCE_CLASS: ClassVar[str] = "Nonconformity"
    target: VersionRef
    description: Label
    status: Literal["suspected", "investigating", "confirmed", "closed", "reopened"]
    recorded_at: datetime
    evidence: tuple[VersionRef, ...] = ()
    previous: VersionRef | None = None
    corrective_actions: tuple[VersionRef, ...] = ()
    closure_evidence: tuple[VersionRef, ...] = ()
    reopening_reason: Label | None = None

    @model_validator(mode="after")
    def finding_history(self):
        aware(self.recorded_at)
        for label, values in (("finding evidence", self.evidence), ("action", self.corrective_actions),
                              ("closure evidence", self.closure_evidence)):
            unique(values, label)
        if self.record_version == 1:
            if self.previous is not None or self.status not in ("suspected", "investigating", "confirmed"):
                raise ValueError("new finding cannot be closed/reopened")
        elif self.previous != VersionRef(identity=self.entity_id, version=self.record_version - 1):
            raise ValueError("previous finding version must be adjacent")
        if self.status == "confirmed" and not self.evidence:
            raise ValueError("confirmation requires evidence")
        if (self.status == "closed") != bool(self.closure_evidence):
            raise ValueError("closure status and evidence must agree")
        if (self.status == "reopened") != (self.reopening_reason is not None):
            raise ValueError("reopening requires explicit reason")
        return self

    def validate_previous(self, previous: "Nonconformity") -> None:
        if (self.previous != previous.ref() or self.target != previous.target or
                self.recorded_at < previous.recorded_at):
            raise ValueError("finding history context mismatch")
        legal = {"suspected": {"investigating", "confirmed", "closed"},
                 "investigating": {"investigating", "confirmed", "closed"},
                 "confirmed": {"confirmed", "closed"}, "closed": {"reopened"},
                 "reopened": {"investigating", "confirmed", "closed"}}
        if self.status not in legal[previous.status]:
            raise ValueError("invalid finding lifecycle edge")
