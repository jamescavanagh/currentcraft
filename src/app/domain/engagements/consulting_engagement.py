"""V1 capture proposal. Sources, invariants and open decisions: docs/domain/V1_DOMAIN.md."""
from typing import ClassVar, Literal
from pydantic import Field
from app.domain.versioning import VersionedEntity
from app.domain.shared.facts import Fact, unknown
from app.domain.shared.identity import Text, ProjectId, PartyId


class Consultant(VersionedEntity):
    """Consulting engagement; approvals require explicit scoped human authority."""
    SOURCE_CLASS: ClassVar[str] = 'Consultant'
    kind: Literal["consultant"] = "consultant"
    party_id: PartyId
    project_id: ProjectId
    role: Fact[Text] = Field(default_factory=unknown)
