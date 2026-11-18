"""Task-linked review capture; no implied release or approval authority."""
from typing import ClassVar, Literal
from pydantic import Field
from app.domain.versioning import VersionedEntity
from app.domain.shared.facts import Fact, unknown
from app.domain.shared.identity import ProjectId, TaskId, Text


class ReviewItem(VersionedEntity):
    """Review request or finding, distinct from an authorized decision."""

    SOURCE_CLASS: ClassVar[str] = 'ReviewItem'
    kind: Literal["review_item"] = "review_item"
    project_id: ProjectId
    task_id: TaskId
    finding: Fact[Text] = Field(default_factory=unknown)
