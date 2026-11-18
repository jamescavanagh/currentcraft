"""Task-linked work capture; process execution remains a separate contract."""
from typing import ClassVar, Literal
from pydantic import Field
from app.domain.versioning import VersionedEntity
from app.domain.shared.facts import Fact, unknown
from app.domain.shared.identity import ProjectId, TaskId, Text


class WorkItem(VersionedEntity):
    """Source-reported work item; construction does not execute it."""

    SOURCE_CLASS: ClassVar[str] = 'WorkItem'
    kind: Literal["work_item"] = "work_item"
    project_id: ProjectId
    task_id: TaskId
    description: Fact[Text] = Field(default_factory=unknown)
