"""P4 complete gate evaluation, not decision or authorization."""
from datetime import datetime
from typing import ClassVar
from pydantic import Field, model_validator
from app.domain.shared.versioning import P4Record, VersionRef, aware, exact, unique
from .gate_criterion_result import GateCriterionResult
from .quality_gate_definition import QualityGateDefinition


class QualityGateInstance(P4Record):
    """Evaluation of every pinned criterion against one exact target."""
    SOURCE_CLASS: ClassVar[str] = "QualityGateInstance"
    definition: VersionRef
    target: VersionRef
    results: tuple[GateCriterionResult, ...] = Field(min_length=1)
    evaluated_at: datetime

    @model_validator(mode="after")
    def result_targets(self):
        aware(self.evaluated_at)
        unique(tuple(r.definition.identity for r in self.results), "criterion result")
        unique(tuple(r.entity_id for r in self.results), "result identity")
        if any(r.target != self.target or r.evaluated_at > self.evaluated_at for r in self.results):
            raise ValueError("criterion target/time mismatch")
        return self

    def passes(self, definition: QualityGateDefinition) -> bool:
        exact(self.definition, definition)
        criteria = {c.ref(): c for c in definition.criteria}
        if {r.definition for r in self.results} != set(criteria):
            raise ValueError("evaluation must cover exact criterion versions")
        blocked = [r.blocks(criteria[r.definition]) for r in self.results]
        return not any(blocked)
