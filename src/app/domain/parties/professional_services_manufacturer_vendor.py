"""V1 capture proposal. Sources, invariants and open decisions: docs/domain/V1_DOMAIN.md."""
from typing import ClassVar, Literal
from app.domain.versioning import VersionedEntity
from app.domain.shared.identity import PartyId


class ProfessionalServicesManufacturerVendor(VersionedEntity):
    """Manufacturer selling professional services. No overlap/exclusivity policy is imposed."""
    SOURCE_CLASS: ClassVar[str] = '(addition)'
    kind: Literal["professional_services_manufacturer_vendor"] = "professional_services_manufacturer_vendor"
    party_id: PartyId
