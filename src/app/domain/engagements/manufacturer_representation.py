"""V1 capture proposal. Sources, invariants and open decisions: docs/domain/V1_DOMAIN.md."""
from typing import ClassVar, Literal
from app.domain.versioning import VersionedEntity
from app.domain.shared.identity import ProjectId, PartyId


class ManufacturerRep(VersionedEntity):
    """Contextual representation, not identity inheritance."""
    SOURCE_CLASS: ClassVar[str] = 'ManufacturerRep'
    kind: Literal["manufacturer_rep"] = "manufacturer_rep"
    representative_party_id: PartyId
    manufacturer_party_id: PartyId
    project_id: ProjectId
