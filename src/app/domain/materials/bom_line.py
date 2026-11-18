"""V1 capture proposal. Sources, invariants and open decisions: docs/domain/V1_DOMAIN.md."""
from typing import ClassVar, Literal
from pydantic import Field
from app.domain.versioning import VersionedEntity
from app.domain.shared.facts import Fact, unknown
from app.domain.shared.identity import ProductId, BOMId
from app.domain.shared.quantities import Quantity


class BOMLine(VersionedEntity):
    """A product quantity in one BOM; no serialized units are manufactured."""
    SOURCE_CLASS: ClassVar[str] = '(addition)'
    kind: Literal["bom_line"] = "bom_line"
    bom_id: BOMId
    product_definition_id: ProductId
    quantity: Fact[Quantity] = Field(default_factory=unknown)
