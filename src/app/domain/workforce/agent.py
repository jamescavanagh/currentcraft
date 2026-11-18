"""V1 capture proposal. Sources, invariants and open decisions: docs/domain/V1_DOMAIN.md."""
from typing import ClassVar, Literal
from pydantic import Field
from app.domain.shared.facts import Fact, unknown
from app.domain.shared.identity import Text
from app.domain.workforce.resource import Resource


class Agent(Resource):
    """AI resource; no implied human authority."""
    SOURCE_CLASS: ClassVar[str] = '(addition)'
    kind: Literal["agent"] = "agent"
    model_reference: Fact[Text] = Field(default_factory=unknown)
