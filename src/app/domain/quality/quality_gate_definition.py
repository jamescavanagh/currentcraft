"""P4 generic human gate definitions."""
from typing import ClassVar
from pydantic import Field, model_validator
from app.domain.shared.versioning import Code, P4Record, unique
from .gate_criterion_definition import GateCriterionDefinition
from .gate_approval_requirement import GateApprovalRequirement


class QualityGateDefinition(P4Record):
    """Criteria and human approval requirements; automatic policy stays separate."""
    SOURCE_CLASS: ClassVar[str] = "QualityGateDefinition"
    code: Code
    criteria: tuple[GateCriterionDefinition, ...] = Field(min_length=1)
    approval_requirements: tuple[GateApprovalRequirement, ...] = ()

    @model_validator(mode="after")
    def unique_definitions(self):
        unique(tuple(c.entity_id for c in self.criteria), "criterion identity")
        unique(tuple(c.code for c in self.criteria), "criterion code")
        unique(tuple(r.entity_id for r in self.approval_requirements), "approval requirement")
        return self
