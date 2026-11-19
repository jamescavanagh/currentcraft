"""V1 capture proposal. Sources, invariants and open decisions: docs/domain/V1_DOMAIN.md."""
from typing import ClassVar, Literal
from uuid import UUID
from pydantic import Field
from app.domain.versioning import VersionedEntity
from app.domain.shared.facts import Fact, unknown
from app.domain.shared.identity import Text, PartyId
from app.domain.shared.contexts import Context


class Consultant(VersionedEntity):
    """Consulting engagement; approvals require explicit scoped human authority."""
    SOURCE_CLASS: ClassVar[str] = 'Consultant'
    kind: Literal["consultant"] = "consultant"
    party_id: PartyId
    context: Context
    role: Fact[Text] = Field(default_factory=unknown)
    scope: Fact[Text] = Field(default_factory=unknown)
    approval_claim_ids: tuple[UUID, ...] = ()
