"""P4 correction implementation, separate from suspicion and verification."""
from datetime import datetime
from typing import ClassVar, Literal
from uuid import UUID
from pydantic import model_validator
from app.domain.shared.versioning import Label, P4Record, VersionRef, aware, exact, unique
from .verification_activity import VerificationActivity


class CorrectiveAction(P4Record):
    """Versioned action with configurable independent verification."""
    SOURCE_CLASS: ClassVar[str] = "CorrectiveAction"
    nonconformity: VersionRef
    target: VersionRef
    description: Label
    status: Literal["proposed", "in_progress", "implemented", "verified", "closed"]
    independent_verification_required: bool = False
    implemented_by: UUID | None = None
    implemented_at: datetime | None = None
    implemented_version: VersionRef | None = None
    implementation_evidence: tuple[VersionRef, ...] = ()
    verifications: tuple[VersionRef, ...] = ()

    @model_validator(mode="after")
    def implementation(self):
        unique(self.implementation_evidence, "implementation evidence")
        unique(self.verifications, "verification reference")
        implemented = self.status in ("implemented", "verified", "closed")
        if implemented:
            if (self.implemented_by is None or self.implemented_at is None or
                    not self.implementation_evidence or self.implemented_version is None):
                raise ValueError("implemented status requires actor, time, version and evidence")
            aware(self.implemented_at)
            if (self.implemented_version.identity != self.entity_id or
                    self.implemented_version.version > self.record_version):
                raise ValueError("invalid implementation version")
        elif (self.implemented_by is not None or self.implemented_at is not None or
              self.implemented_version is not None or self.implementation_evidence or self.verifications):
            raise ValueError("unimplemented action cannot carry implementation/verification")
        if self.status == "implemented" and self.implemented_version != self.ref():
            raise ValueError("implemented snapshot must reference itself")
        if self.status in ("verified", "closed") and (
                not self.verifications or self.implemented_version.version >= self.record_version):
            raise ValueError("verified/closed action requires prior implementation and verification")
        return self

    def validate_verifications(self, activities: tuple[VerificationActivity, ...],
                               implemented_action: "CorrectiveAction") -> None:
        if self.implemented_version is None:
            raise ValueError("implementation reference required")
        exact(self.implemented_version, implemented_action)
        fields = ("entity_id", "target", "nonconformity", "implemented_by", "implemented_at",
                  "implementation_evidence", "independent_verification_required")
        if implemented_action.status != "implemented" or any(
                getattr(self, field) != getattr(implemented_action, field) for field in fields):
            raise ValueError("implementation context changed")
        if {v.ref() for v in activities} != set(self.verifications) or len(activities) != len(self.verifications):
            raise ValueError("exact verification set required")
        for activity in activities:
            if (activity.action != self.implemented_version or activity.target != self.target or
                    activity.verified_at < self.implemented_at):
                raise ValueError("verification action/target/time mismatch")
            if self.independent_verification_required and activity.verifier_id == self.implemented_by:
                raise ValueError("independent verification required")
        if self.status in ("verified", "closed") and any(v.result != "pass" for v in activities):
            raise ValueError("unresolved verification findings prevent closure")
