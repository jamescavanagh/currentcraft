from typing import Literal
"""Shared party identity, independent of resource and contextual role."""
from pydantic import Field
from app.domain.versioning import VersionedEntity
from app.domain.shared.facts import Fact, unknown
from app.domain.shared.identity import Text


class Party(VersionedEntity):
    """Party identity; organization/person classification remains unspecified."""
    kind: Literal["party"] = "party"
    name: Fact[Text] = Field(default_factory=unknown)
