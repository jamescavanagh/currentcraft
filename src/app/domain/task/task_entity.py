"""V1 capture proposal. Sources, invariants and open decisions: docs/domain/V1_DOMAIN.md."""
from typing import ClassVar, Literal
from pydantic import Field
from app.domain.versioning import VersionedEntity
from app.domain.shared.facts import Fact, unknown
from app.domain.shared.identity import Text, ProjectId, PhaseId, SubsystemId, WBSId


class Task(VersionedEntity):
    """Business task; not an external task or process execution."""
    SOURCE_CLASS: ClassVar[str] = 'Task'
    kind: Literal["task"] = "task"
    project_id: ProjectId
    name: Fact[Text] = Field(default_factory=unknown)
    subsystem_id: Fact[SubsystemId] = Field(default_factory=unknown)
    phase_id: Fact[PhaseId] = Field(default_factory=unknown)
    wbs_id: Fact[WBSId] = Field(default_factory=unknown)
