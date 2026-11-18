"""V1 capture proposal. Sources, invariants and open decisions: docs/domain/V1_DOMAIN.md."""
from typing import ClassVar, Literal
from app.domain.versioning import VersionedEntity
from app.domain.shared.identity import PartyId


class SubcontractorFreelancerVendor(VersionedEntity):
    """Subcontractor or freelancer vendor classification. No overlap/exclusivity policy is imposed."""
    SOURCE_CLASS: ClassVar[str] = '(addition)'
    kind: Literal["subcontractor_freelancer_vendor"] = "subcontractor_freelancer_vendor"
    party_id: PartyId
