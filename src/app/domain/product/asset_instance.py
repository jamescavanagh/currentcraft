"""V1 capture proposal. Sources, invariants and open decisions: docs/domain/V1_DOMAIN.md."""
from typing import ClassVar, Literal
from pydantic import Field
from app.domain.versioning import VersionedEntity
from app.domain.shared.facts import Fact, unknown
from app.domain.shared.identity import Text, ProjectId, ProductId


class AssetInstance(VersionedEntity):
    """Existing physical unit; capture does not create or consume stock."""
    SOURCE_CLASS: ClassVar[str] = '(addition)'
    kind: Literal["asset_instance"] = "asset_instance"
    project_id: ProjectId
    product_definition_id: ProductId
    serial: Fact[Text] = Field(default_factory=unknown)
    mac_address: Fact[Text] = Field(default_factory=unknown)
    ip_address: Fact[Text] = Field(default_factory=unknown)
    firmware: Fact[Text] = Field(default_factory=unknown)
    installation: Fact[Text] = Field(default_factory=unknown)
