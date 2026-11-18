"""V1 capture proposal. Sources, invariants and open decisions: docs/domain/V1_DOMAIN.md."""
from typing import ClassVar, Literal
from pydantic import Field, model_validator
from app.domain.versioning import VersionedEntity
from app.domain.shared.facts import Fact, unknown
from app.domain.shared.identity import ProjectId, ProductId, AssetId, ShipmentId
from app.domain.shared.quantities import Quantity


class Shipment(VersionedEntity):
    """Shipment header; lines reference this ID, no custody workflow inferred."""
    SOURCE_CLASS: ClassVar[str] = '(addition)'
    kind: Literal["shipment"] = "shipment"
    project_id: ProjectId


class ShipmentLine(VersionedEntity):
    """One existing asset OR one product quantity. No custody mutation."""
    kind: Literal["shipment_line"] = "shipment_line"
    shipment_id: ShipmentId
    asset_id: Fact[AssetId] = Field(default_factory=unknown)
    product_definition_id: Fact[ProductId] = Field(default_factory=unknown)
    quantity: Fact[Quantity] = Field(default_factory=unknown)

    @model_validator(mode="after")
    def line_variant(self):
        asset = self.asset_id.value is not None
        product = self.product_definition_id.value is not None
        quantity = self.quantity.value is not None
        if not ((asset and not product and not quantity) or (not asset and product and quantity)):
            raise ValueError("line needs exactly an existing asset or a product with quantity")
        return self
