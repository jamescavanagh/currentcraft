"""V1 capture proposal. Sources, invariants and open decisions: docs/domain/V1_DOMAIN.md."""
from typing import ClassVar, Literal
from uuid import UUID
from pydantic import Field
from app.domain.versioning import VersionedEntity
from app.domain.shared.facts import Fact, unknown
from app.domain.shared.identity import Text, ProjectId


class RFI(VersionedEntity):
    """Question/response and contextual impact links; not approval."""
    SOURCE_CLASS: ClassVar[str] = '(addition)'
    kind: Literal["rfi"] = "rfi"
    project_id: ProjectId
    question: Fact[Text] = Field(default_factory=unknown)
    response: Fact[Text] = Field(default_factory=unknown)
    impact_ids: tuple[UUID, ...] = ()
