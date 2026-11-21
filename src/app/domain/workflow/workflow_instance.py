"""P4 workflow subject capture; history commitment belongs to the application."""
from datetime import datetime
from typing import ClassVar
from pydantic import model_validator
from app.domain.shared.versioning import P4Record, VersionRef, aware, exact
from .workflow_definition import WorkflowDefinition


class WorkflowInstance(P4Record):
    """Run pinned to definition, target and state versions."""
    SOURCE_CLASS: ClassVar[str] = "WorkflowInstance"
    definition: VersionRef
    target: VersionRef
    current_state: VersionRef
    started_at: datetime
    last_transition: VersionRef | None = None

    @model_validator(mode="after")
    def initial_history(self):
        aware(self.started_at)
        if (self.record_version == 1) != (self.last_transition is None):
            raise ValueError("initial run has no transition; later versions require one")
        return self

    def validate_definition(self, definition: WorkflowDefinition) -> None:
        exact(self.definition, definition)
        states = {state.ref(): state for state in definition.states}
        if self.current_state not in states:
            raise ValueError("unknown state version")
        if self.record_version == 1 and not states[self.current_state].initial:
            raise ValueError("new run must start in initial state")
