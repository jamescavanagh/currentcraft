"""V1 capture proposal. Sources, invariants and open decisions: docs/domain/V1_DOMAIN.md."""
from typing import ClassVar, Literal
from app.domain.versioning import VersionedEntity
from app.domain.shared.identity import PartyId


class Vendor(VersionedEntity):
    """Vendor classification of a party; no overlap policy imposed."""
    SOURCE_CLASS: ClassVar[str] = 'Vendor'
    kind: Literal["vendor"] = "vendor"
    party_id: PartyId
