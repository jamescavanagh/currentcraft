"""Project system identity; design: docs/domain/P0_P3_CAPTURE.md."""
from typing import ClassVar, Literal
from pydantic import Field
from app.domain.versioning import VersionedEntity
from app.domain.shared.facts import Fact, unknown
from app.domain.shared.identity import ProjectId, Text


class System(VersionedEntity):
    """Named project system; no inferred subsystem allocation."""

    SOURCE_CLASS: ClassVar[str] = 'System'
    kind: Literal["system"] = "system"
    project_id: ProjectId
    name: Fact[Text] = Field(default_factory=unknown)
