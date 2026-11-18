"""V1 capture proposal. Sources, invariants and open decisions: docs/domain/V1_DOMAIN.md."""
from typing import ClassVar, Literal
from pydantic import Field
from app.domain.versioning import VersionedEntity
from app.domain.shared.facts import Fact, unknown
from app.domain.shared.identity import Text, ProjectId
from app.domain.shared.facts import TimeWindow


class Phase(VersionedEntity):
    """Project lifecycle phase; not a simulator phase or execution stage."""
    SOURCE_CLASS: ClassVar[str] = 'Phase'
    kind: Literal["phase"] = "phase"
    project_id: ProjectId
    name: Fact[Text] = Field(default_factory=unknown)
    baseline_window: Fact[TimeWindow] = Field(default_factory=unknown)
    actual_window: Fact[TimeWindow] = Field(default_factory=unknown)
