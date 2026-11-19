"""V1 capture proposal. Sources, invariants and open decisions: docs/domain/V1_DOMAIN.md."""
from typing import ClassVar, Literal
from pydantic import Field
from app.domain.versioning import VersionedEntity
from app.domain.shared.identity import ProjectId, PartyId, Text
from app.domain.shared.facts import Fact, DateBounds, unknown


class ManufacturerRep(VersionedEntity):
    """Contextual representation, not identity inheritance."""
    SOURCE_CLASS: ClassVar[str] = 'ManufacturerRep'
    kind: Literal["manufacturer_rep"] = "manufacturer_rep"
    representative_party_id: PartyId
    manufacturer_party_id: PartyId
    territory: Fact[Text] = Field(default_factory=unknown)
    agreement_dates: DateBounds = Field(default_factory=DateBounds)
    contact_party_ids: Fact[tuple[PartyId, ...]] = Field(default_factory=unknown)
    project_id: Fact[ProjectId] = Field(default_factory=unknown)
