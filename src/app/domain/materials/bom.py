"""V1 capture proposal. Sources, invariants and open decisions: docs/domain/V1_DOMAIN.md."""
from typing import ClassVar, Literal
from pydantic import Field
from app.domain.versioning import VersionedEntity
from app.domain.shared.facts import Fact, unknown
from app.domain.shared.identity import ProjectId


class BOM(VersionedEntity):
    """BOM identity; stage changes never merge identities or create orders."""
    SOURCE_CLASS: ClassVar[str] = '(addition)'
    kind: Literal["bom"] = "bom"
    project_id: ProjectId
    stage: Fact[Literal["rom", "material_list", "po"]] = Field(default_factory=unknown)
