"""P4 human milestone sign-off of an exact evidenced occurrence."""
from datetime import datetime
from typing import ClassVar
from uuid import UUID
from pydantic import model_validator
from app.domain.shared.versioning import P4Record, VersionRef, aware, exact
from app.domain.project.milestone import Milestone
from .approval import Approval
from .gate_approval_requirement import GateApprovalRequirement


class MilestoneSignOff(P4Record):
    """Separate scoped sign-off; neither scheduled date nor occurrence grants it."""
    SOURCE_CLASS: ClassVar[str] = "MilestoneSignOff"
    milestone: VersionRef
    approval: Approval
    signed_at: datetime

    @model_validator(mode="after")
    def scoped_signoff(self):
        aware(self.signed_at)
        if (self.approval.target != self.milestone or self.approval.scope != "milestone_sign_off" or
                self.approval.evaluation is not None or self.approval.outcome != "granted" or
                self.approval.recorded_at > self.signed_at or (
                    self.approval.expires_at is not None and self.signed_at >= self.approval.expires_at)):
            raise ValueError("invalid scoped milestone approval")
        return self

    def validate_context(self, milestone: Milestone, requirement: GateApprovalRequirement,
                         *, executor_id: UUID | None = None) -> None:
        exact(self.milestone, milestone)
        if requirement.minimum_approvers != 1:
            raise ValueError("single sign-off cannot satisfy multi-person quorum")
        if milestone.occurred_at is None or milestone.occurred_at > self.signed_at:
            raise ValueError("evidenced occurrence must precede sign-off")
        self.approval.validate_requirement(requirement, target=milestone.ref(), evaluation=None,
                                          at=self.signed_at, executor_id=executor_id)
