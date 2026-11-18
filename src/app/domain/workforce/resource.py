from typing import Literal
"""Execution identity. Classification never supplies permission."""
from pydantic import Field
from app.domain.versioning import VersionedEntity
from app.domain.shared.facts import Fact, unknown
from app.domain.shared.identity import PartyId, Text


class Resource(VersionedEntity):
    """Resource identity, separate from a party's identity and decision rights."""
    kind: Literal["resource"] = "resource"
    party_id: Fact[PartyId] = Field(default_factory=unknown)
    name: Fact[Text] = Field(default_factory=unknown)

    def permits(self, permission: str) -> bool:
        """No permission policy exists: every permission, including unknowns, is denied."""
        return False
