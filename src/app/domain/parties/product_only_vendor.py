"""V1 capture proposal. Sources, invariants and open decisions: docs/domain/V1_DOMAIN.md."""
from typing import ClassVar, Literal
from app.domain.versioning import VersionedEntity
from app.domain.shared.identity import PartyId


class ProductOnlyVendor(VersionedEntity):
    """Product-only distributor or entity. No overlap/exclusivity policy is imposed."""
    SOURCE_CLASS: ClassVar[str] = '(addition)'
    kind: Literal["product_only_vendor"] = "product_only_vendor"
    party_id: PartyId
