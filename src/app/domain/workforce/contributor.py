"""V1 capture proposal. Sources, invariants and open decisions: docs/domain/V1_DOMAIN.md."""
from typing import ClassVar, Literal
from pydantic import Field
from app.domain.shared.facts import Fact, unknown
from app.domain.shared.identity import PartyId
from app.domain.workforce.resource import Resource


class Contributor(Resource):
    """Third-party labor; provider is distinct from a booking platform."""
    SOURCE_CLASS: ClassVar[str] = 'Contributor'
    kind: Literal["contributor"] = "contributor"
    provider_party_id: Fact[PartyId] = Field(default_factory=unknown)
