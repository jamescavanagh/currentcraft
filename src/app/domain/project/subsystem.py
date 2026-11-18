"""V1 capture proposal. Sources, invariants and open decisions: docs/domain/V1_DOMAIN.md."""
from typing import ClassVar, Literal
from pydantic import Field
from app.domain.versioning import VersionedEntity
from app.domain.shared.facts import Fact, unknown
from app.domain.shared.identity import Text, ProjectId


class Subsystem(VersionedEntity):
    """Project subsystem identity."""
    SOURCE_CLASS: ClassVar[str] = 'Subsystem'
    kind: Literal["subsystem"] = "subsystem"
    project_id: ProjectId
    name: Fact[Text] = Field(default_factory=unknown)
