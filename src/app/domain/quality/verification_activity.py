"""P4 verification event; independence is a configured action requirement."""
from datetime import datetime
from typing import ClassVar, Literal
from uuid import UUID
from pydantic import Field, model_validator
from app.domain.shared.versioning import P4Record, VersionRef, aware, unique


class VerificationActivity(P4Record):
    """Evidenced verification of an exact correction and target version."""
    SOURCE_CLASS: ClassVar[str] = "VerificationActivity"
    action: VersionRef
    target: VersionRef
    verifier_id: UUID
    result: Literal["pass", "fail", "inconclusive"]
    evidence: tuple[VersionRef, ...] = Field(min_length=1)
    verified_at: datetime

    @model_validator(mode="after")
    def verification_time(self):
        aware(self.verified_at)
        unique(self.evidence, "verification evidence")
        return self
