"""P4 transition rules; no execution or implicit authority."""
from typing import ClassVar, Literal
from pydantic import model_validator
from app.domain.shared.versioning import Code, Label, P4Record, VersionRef


class TransitionDefinition(P4Record):
    """Versioned directed edge with explicit human or automatic control path."""
    SOURCE_CLASS: ClassVar[str] = "TransitionDefinition"
    code: Code
    from_state: VersionRef
    to_state: VersionRef
    purpose: Label
    control: Literal["none", "human_gate", "automatic_policy"]
    gate: VersionRef | None = None
    policy_version: Label | None = None
    requires_new_attempt: bool = False

    @model_validator(mode="after")
    def control_path(self):
        if self.from_state.identity == self.to_state.identity:
            raise ValueError("self transition is not supported")
        if self.control == "human_gate":
            if self.gate is None or self.policy_version is not None:
                raise ValueError("human control requires gate, not automatic policy")
        elif self.control == "automatic_policy":
            if self.policy_version is None or self.gate is not None:
                raise ValueError("automatic control requires policy, not a human gate")
        elif self.gate is not None or self.policy_version is not None:
            raise ValueError("uncontrolled edge cannot carry gate/policy")
        return self
