"""V1 capture proposal. Sources, invariants and open decisions: docs/domain/V1_DOMAIN.md."""
from typing import ClassVar, Literal
from app.domain.versioning import VersionedEntity
from app.domain.shared.identity import PartyId


class Client(VersionedEntity):
    """Client classification of a party; no inferred rights."""
    SOURCE_CLASS: ClassVar[str] = 'Client'
    kind: Literal["client"] = "client"
    party_id: PartyId
