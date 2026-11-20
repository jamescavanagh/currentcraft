"""P4 transition record; application verifies commitment and automatic permits."""
from datetime import datetime
from typing import ClassVar
from pydantic import Field, model_validator
from app.domain.shared.versioning import Code, Label, P4Record, VersionRef, aware, exact
from app.domain.quality.gate_decision import GateDecision
from .workflow_definition import WorkflowDefinition
from .workflow_instance import WorkflowInstance


class StateTransition(P4Record):
    """Exact workflow edge and execution link; never a second execution log."""
    SOURCE_CLASS: ClassVar[str] = "StateTransition"
    workflow: VersionRef
    definition: VersionRef
    target: VersionRef
    from_state: VersionRef
    to_state: VersionRef
    execution_id: Code
    committed_workflow_version: int = Field(ge=2, strict=True)
    gate_decision: VersionRef | None = None
    policy_evaluation: VersionRef | None = None
    policy_version: Label | None = None
    attempt: VersionRef | None = None
    occurred_at: datetime

    @model_validator(mode="after")
    def adjacency(self):
        aware(self.occurred_at)
        if self.committed_workflow_version != self.workflow.version + 1:
            raise ValueError("workflow version must advance by one")
        if self.from_state.identity == self.to_state.identity:
            raise ValueError("self transition is not supported")
        if self.gate_decision is not None and self.policy_evaluation is not None:
            raise ValueError("human and automatic decision paths are distinct")
        if (self.policy_evaluation is None) != (self.policy_version is None):
            raise ValueError("automatic evaluation and policy version go together")
        return self

    def validate_context(self, instance: WorkflowInstance, definition: WorkflowDefinition,
                         decision: GateDecision | None = None) -> None:
        exact(self.workflow, instance)
        instance.validate_definition(definition)
        edges = {edge.ref(): edge for edge in definition.transitions}
        edge = edges.get(self.definition)
        if edge is None or (self.from_state, self.to_state) != (edge.from_state, edge.to_state):
            raise ValueError("unknown or mismatched transition definition")
        if self.from_state != instance.current_state or self.target != instance.target:
            raise ValueError("transition state/target mismatch")
        if self.occurred_at < instance.started_at:
            raise ValueError("transition predates run")
        if edge.requires_new_attempt and self.attempt is None:
            raise ValueError("new auditable attempt required")
        if edge.control == "human_gate":
            if self.gate_decision is None or decision is None or self.policy_evaluation is not None:
                raise ValueError("human transition requires exact decision")
            exact(self.gate_decision, decision)
            if (decision.execution_id != self.execution_id or decision.target != self.target or
                    decision.transition_definition != edge.ref() or decision.effect != "release" or
                    decision.recorded_at > self.occurred_at):
                raise ValueError("decision cannot authorize this transition")
        elif edge.control == "automatic_policy":
            if (self.policy_evaluation is None or self.policy_version != edge.policy_version or
                    self.gate_decision is not None or decision is not None):
                raise ValueError("automatic transition requires separate policy evaluation")
        elif self.gate_decision is not None or self.policy_evaluation is not None or decision is not None:
            raise ValueError("uncontrolled transition cannot carry a decision")
