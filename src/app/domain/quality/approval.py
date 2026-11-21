"""P4 scoped human approval capture; authority evidence must be resolved later."""
from datetime import datetime
from typing import ClassVar, Literal
from uuid import UUID
from pydantic import Field, model_validator
from app.domain.shared.versioning import Code, Label, P4Record, VersionRef, aware, exact, unique
from .gate_approval_requirement import GateApprovalRequirement


class Approval(P4Record):
    """Human response scoped to requirement, target, evaluation and purpose."""
    SOURCE_CLASS: ClassVar[str] = "Approval"
    requirement: VersionRef
    target: VersionRef
    evaluation: VersionRef | None = None
    actor_id: UUID
    holder_role: Code
    scope: Code
    purpose: Label
    authority_evidence: tuple[VersionRef, ...] = Field(min_length=1)
    outcome: Literal["granted", "rejected", "revoked"]
    recorded_at: datetime
    expires_at: datetime | None = None

    @model_validator(mode="after")
    def times_and_evidence(self):
        aware(self.recorded_at)
        unique(self.authority_evidence, "authority evidence")
        if self.expires_at is not None and aware(self.expires_at) <= self.recorded_at:
            raise ValueError("approval expiry must follow response")
        return self

    def validate_requirement(self, requirement: GateApprovalRequirement, *, target: VersionRef,
                             evaluation: VersionRef | None, at: datetime,
                             executor_id: UUID | None = None) -> None:
        exact(self.requirement, requirement)
        aware(at)
        if (self.target, self.evaluation) != (target, evaluation):
            raise ValueError("approval target/evaluation mismatch")
        if (self.scope, self.purpose, self.holder_role) != (
                requirement.scope, requirement.purpose, requirement.holder_role):
            raise ValueError("approval scope/purpose/role mismatch")
        if self.outcome != "granted" or at < self.recorded_at or (
                self.expires_at is not None and at >= self.expires_at):
            raise ValueError("approval is not currently granted")
        if requirement.allowed_actors and self.actor_id not in requirement.allowed_actors:
            raise ValueError("actor not allowed")
        if requirement.independent_from_executor and (executor_id is None or self.actor_id == executor_id):
            raise ValueError("independent approver required")
