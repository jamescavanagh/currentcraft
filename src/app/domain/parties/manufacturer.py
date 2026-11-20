"""Manufacturer classification of an existing party; no inferred rights."""
from typing import ClassVar, Literal
from app.domain.versioning import VersionedEntity
from app.domain.shared.identity import PartyId


class Manufacturer(VersionedEntity):
    """A maker party; representation remains a separate contextual record."""

    SOURCE_CLASS: ClassVar[str] = 'Manufacturer'
    kind: Literal["manufacturer"] = "manufacturer"
    party_id: PartyId
