"""P4 criterion definitions, not evaluated results."""
from typing import ClassVar, Literal
from pydantic import model_validator
from app.domain.shared.versioning import Code, Label, P4Record


class GateCriterionDefinition(P4Record):
    """Versioned predicate and requirement; applicability is not guessed."""
    SOURCE_CLASS: ClassVar[str] = "GateCriterionDefinition"
    code: Code
    requirement: Literal["mandatory", "conditional", "informational"]
    predicate_version: Label
    description: Label
    applicability_rule: Label | None = None

    @model_validator(mode="after")
    def conditional_rule(self):
        if self.requirement == "conditional" and self.applicability_rule is None:
            raise ValueError("conditional criterion requires applicability rule")
        return self
