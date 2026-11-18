"""V1 capture proposal. Sources, invariants and open decisions: docs/domain/V1_DOMAIN.md."""
from typing import ClassVar, Literal
from app.domain.versioning import VersionedEntity
from app.domain.shared.identity import PartyId


class LaborPlatformVendor(VersionedEntity):
    """Platform; separate from the party providing booked labor. No overlap/exclusivity policy is imposed."""
    SOURCE_CLASS: ClassVar[str] = '(addition)'
    kind: Literal["labor_platform_vendor"] = "labor_platform_vendor"
    party_id: PartyId
