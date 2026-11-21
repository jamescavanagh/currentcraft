"""P4 evidence/applicability result with explicit version pins."""
from datetime import datetime
from typing import ClassVar, Literal
from pydantic import model_validator
from app.domain.shared.versioning import Label, P4Record, VersionRef, aware, exact, unique
from .gate_criterion_definition import GateCriterionDefinition


class GateCriterionResult(P4Record):
    """Evaluation result; passing a criterion never grants approval."""
    SOURCE_CLASS: ClassVar[str] = "GateCriterionResult"
    definition: VersionRef
    target: VersionRef
    applicability: Literal["yes", "no", "unknown"]
    evidence_condition: Literal["sufficient", "missing", "conflicting", "stale", "fails"]
    result: Literal["pass", "fail", "missing", "conflicting", "stale", "not_applicable"]
    evidence: tuple[VersionRef, ...] = ()
    applicability_reason: Label | None = None
    evaluated_at: datetime

    @model_validator(mode="after")
    def local_truth(self):
        aware(self.evaluated_at)
        unique(self.evidence, "evidence version")
        expected = ("not_applicable" if self.applicability == "no" else
                    "missing" if self.applicability == "unknown" else
                    {"sufficient": "pass", "fails": "fail"}.get(self.evidence_condition, self.evidence_condition))
        if self.result != expected:
            raise ValueError("result contradicts applicability/evidence")
        if self.applicability == "no" and self.applicability_reason is None:
            raise ValueError("inapplicability requires rationale")
        if self.applicability == "yes" and self.evidence_condition != "missing" and not self.evidence:
            raise ValueError("evidence condition requires exact evidence versions")
        return self

    def blocks(self, definition: GateCriterionDefinition) -> bool:
        exact(self.definition, definition)
        if definition.requirement == "mandatory" and self.applicability == "no":
            raise ValueError("mandatory criterion cannot be inapplicable")
        return definition.requirement != "informational" and self.result not in ("pass", "not_applicable")
