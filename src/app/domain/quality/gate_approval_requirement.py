"""Generic human approval requirement, not automatic publication policy."""
from typing import ClassVar
from uuid import UUID
from pydantic import Field, model_validator
from app.domain.shared.versioning import Code, Label, P4Record, unique


class GateApprovalRequirement(P4Record):
    """Human scope, purpose, quorum and optional independence/actor constraints."""
    SOURCE_CLASS: ClassVar[str] = "GateApprovalRequirement"
    scope: Code
    purpose: Label
    holder_role: Code
    minimum_approvers: int = Field(default=1, ge=1, strict=True)
    allowed_actors: tuple[UUID, ...] = ()
    independent_from_executor: bool = False

    @model_validator(mode="after")
    def quorum(self):
        unique(self.allowed_actors, "allowed actor")
        if self.allowed_actors and len(self.allowed_actors) < self.minimum_approvers:
            raise ValueError("quorum exceeds allowed actor set")
        return self
