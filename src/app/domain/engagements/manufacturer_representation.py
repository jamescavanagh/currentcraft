"""V1 capture proposal. Sources, invariants and open decisions: docs/domain/V1_DOMAIN.md."""
from typing import ClassVar, Literal
from app.domain.versioning import VersionedEntity
from app.domain.shared.identity import ProjectId, PartyId
from app.domain.shared.facts import Fact, unknown, TimeWindow
from pydantic import Field
from app.domain.shared.identity import Text


class ManufacturerRep(VersionedEntity):
    """Contextual representation, not identity inheritance."""
    SOURCE_CLASS: ClassVar[str] = 'ManufacturerRep'
    kind: Literal["manufacturer_rep"] = "manufacturer_rep"
    representative_party_id: PartyId
    manufacturer_party_id: PartyId
    project_id: ProjectId
    territory: Fact[Text] = Field(default_factory=unknown)
    agreement_window: Fact[TimeWindow] = Field(default_factory=unknown)
    contact: Fact[Text] = Field(default_factory=unknown)
