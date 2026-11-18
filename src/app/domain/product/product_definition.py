"""V1 capture proposal. Sources, invariants and open decisions: docs/domain/V1_DOMAIN.md."""
from typing import ClassVar, Literal
from pydantic import Field
from app.domain.versioning import VersionedEntity
from app.domain.shared.facts import Fact, unknown
from app.domain.shared.identity import Text, PartyId


class ProductDefinition(VersionedEntity):
    """Catalog definition, with no physical serial identity."""
    SOURCE_CLASS: ClassVar[str] = '(addition)'
    kind: Literal["product_definition"] = "product_definition"
    name: Fact[Text] = Field(default_factory=unknown)
    manufacturer_party_id: Fact[PartyId] = Field(default_factory=unknown)
    model: Fact[Text] = Field(default_factory=unknown)
    is_bulk: Fact[bool] = Field(default_factory=unknown)
