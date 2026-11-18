"""Project location capture; design: docs/domain/P0_P3_CAPTURE.md."""
from typing import ClassVar, Literal
from pydantic import Field
from app.domain.versioning import VersionedEntity
from app.domain.shared.facts import Fact, unknown
from app.domain.shared.identity import ProjectId, Text


class Location(VersionedEntity):
    """Explicit project-scoped location; no inferred physical hierarchy."""

    SOURCE_CLASS: ClassVar[str] = 'Location'
    kind: Literal["location"] = "location"
    project_id: ProjectId
    source_label: Fact[Text] = Field(default_factory=unknown)
