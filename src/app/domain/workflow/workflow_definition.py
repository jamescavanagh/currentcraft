"""P4 immutable workflow vocabulary and topology."""
from typing import ClassVar
from pydantic import Field, model_validator
from app.domain.shared.versioning import Code, P4Record, unique
from .lifecycle_state import LifecycleState
from .transition_definition import TransitionDefinition


class WorkflowDefinition(P4Record):
    """Pinned state/transition set; initial, terminal and reachability rules."""
    SOURCE_CLASS: ClassVar[str] = "WorkflowDefinition"
    code: Code
    states: tuple[LifecycleState, ...] = Field(min_length=2)
    transitions: tuple[TransitionDefinition, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def topology(self):
        unique(tuple(s.entity_id for s in self.states), "state identity")
        unique(tuple(s.code for s in self.states), "state code")
        unique(tuple(t.entity_id for t in self.transitions), "transition identity")
        unique(tuple(t.code for t in self.transitions), "transition code")
        unique(tuple((t.from_state, t.to_state) for t in self.transitions), "edge")
        initial = [s for s in self.states if s.initial]
        if len(initial) != 1 or not any(s.terminal for s in self.states):
            raise ValueError("exactly one initial and at least one terminal state required")
        by_ref = {s.ref(): s for s in self.states}
        for edge in self.transitions:
            if edge.from_state not in by_ref or edge.to_state not in by_ref:
                raise ValueError("transition references unknown state version")
            if by_ref[edge.from_state].terminal:
                raise ValueError("terminal state has an outgoing transition")
        reached = {initial[0].ref()}
        while True:
            expanded = reached | {t.to_state for t in self.transitions if t.from_state in reached}
            if expanded == reached:
                break
            reached = expanded
        if reached != set(by_ref):
            raise ValueError("unreachable lifecycle state")
        return self
