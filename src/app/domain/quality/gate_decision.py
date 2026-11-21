"""P4 human decision, never the automatic publication decision."""
from datetime import datetime
from typing import ClassVar, Literal
from uuid import UUID
from pydantic import Field, model_validator
from app.domain.shared.versioning import Code, Label, P4Record, VersionRef, aware, exact, unique
from app.domain.workflow.transition_definition import TransitionDefinition
from .approval import Approval
from .quality_gate_definition import QualityGateDefinition
from .quality_gate_instance import QualityGateInstance


class GateDecision(P4Record):
    """Human control effect with explicit execution, authority and evaluation links."""
    SOURCE_CLASS: ClassVar[str] = "GateDecision"
    evaluation: VersionRef
    target: VersionRef
    transition_definition: VersionRef
    execution_id: Code
    actor_id: UUID
    scope: Code
    purpose: Label
    authority_evidence: tuple[VersionRef, ...] = Field(min_length=1)
    effect: Literal["hold", "release", "reject", "return"]
    approvals: tuple[Approval, ...] = ()
    recorded_at: datetime

    @model_validator(mode="after")
    def decision_links(self):
        aware(self.recorded_at)
        unique(self.authority_evidence, "decision authority evidence")
        unique(tuple(a.entity_id for a in self.approvals), "approval identity")
        if any(a.target != self.target or a.evaluation != self.evaluation or
               a.recorded_at > self.recorded_at for a in self.approvals):
            raise ValueError("approval decision context mismatch")
        if self.scope != self.effect:
            raise ValueError("decision authority scope must match control effect")
        return self

    def validate_context(self, evaluation: QualityGateInstance, gate: QualityGateDefinition,
                         transition: TransitionDefinition, *, executor_id: UUID | None = None) -> None:
        exact(self.evaluation, evaluation)
        exact(self.transition_definition, transition)
        if (transition.control != "human_gate" or transition.gate != gate.ref() or
                self.target != evaluation.target or self.purpose != transition.purpose or
                self.recorded_at < evaluation.evaluated_at):
            raise ValueError("human decision context mismatch")
        passes = evaluation.passes(gate)
        requirements = {r.ref(): r for r in gate.approval_requirements}
        for approval in self.approvals:
            if approval.requirement not in requirements:
                raise ValueError("unknown approval requirement version")
            approval.validate_requirement(requirements[approval.requirement], target=self.target,
                                          evaluation=self.evaluation, at=self.recorded_at,
                                          executor_id=executor_id)
        if self.effect == "release":
            if not passes:
                raise ValueError("blocking criteria cannot release")
            for ref, requirement in requirements.items():
                actors = {a.actor_id for a in self.approvals if a.requirement == ref}
                if len(actors) < requirement.minimum_approvers:
                    raise ValueError("approval quorum not met")
