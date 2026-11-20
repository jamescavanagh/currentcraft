"""A client subdivision with its own party and parent client classification."""
from typing import ClassVar, Literal
from app.domain.versioning import VersionedEntity
from app.domain.shared.identity import PartyId


class ClientDivision(VersionedEntity):
    """Explicit client subdivision; no inferred purchasing authority."""

    SOURCE_CLASS: ClassVar[str] = 'ClientDivision'
    kind: Literal["client_division"] = "client_division"
    party_id: PartyId
    client_id: PartyId
