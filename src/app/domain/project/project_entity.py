"""V1 capture proposal. Sources, invariants and open decisions: docs/domain/V1_DOMAIN.md."""
from typing import ClassVar, Literal
from pydantic import Field
from app.domain.versioning import VersionedEntity
from app.domain.shared.facts import Fact, unknown
from app.domain.shared.identity import Text
from app.domain.shared.facts import TimeWindow
from app.domain.shared.quantities import Quantity


class Project(VersionedEntity):
    """Project identity, separate from its source business number."""
    SOURCE_CLASS: ClassVar[str] = 'Project'
    kind: Literal["project"] = "project"
    name: Fact[Text] = Field(default_factory=unknown)
    baseline_window: Fact[TimeWindow] = Field(default_factory=unknown)
    actual_window: Fact[TimeWindow] = Field(default_factory=unknown)
    estimated_effort: Fact[Quantity] = Field(default_factory=unknown)
