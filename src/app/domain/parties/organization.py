"""Organization classification of an existing party; no hard-coded company."""
from typing import ClassVar, Literal
from app.domain.versioning import VersionedEntity
from app.domain.shared.identity import PartyId


class Organization(VersionedEntity):
    """A party classified as an organization; classification grants no rights."""

    SOURCE_CLASS: ClassVar[str] = 'Organization'
    kind: Literal["organization"] = "organization"
    party_id: PartyId
