"""V1 capture proposal. Sources, invariants and open decisions: docs/domain/V1_DOMAIN.md."""
from typing import ClassVar, Literal
from pydantic import Field
from app.domain.versioning import VersionedEntity
from app.domain.shared.facts import Fact, unknown
from app.domain.shared.identity import Text, ProjectId, WBSId, PhaseId


class WBS(VersionedEntity):
    """Project work-breakdown identity; nesting is not inferred."""
    SOURCE_CLASS: ClassVar[str] = 'WBS'
    kind: Literal["wbs"] = "wbs"
    project_id: ProjectId
    code: Fact[Text] = Field(default_factory=unknown)
    parent_wbs_id: Fact[WBSId] = Field(default_factory=unknown)
    phase_id: Fact[PhaseId] = Field(default_factory=unknown)
