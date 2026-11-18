"""V1 capture proposal. Sources, invariants and open decisions: docs/domain/V1_DOMAIN.md."""
from typing import ClassVar, Literal
from pydantic import Field
from app.domain.versioning import VersionedEntity
from app.domain.shared.facts import Fact, unknown
from app.domain.shared.identity import ProjectId, PartyId, DocumentId, Text
from uuid import UUID


class Order(VersionedEntity):
    """Commercial order identity, separate from supporting documents."""
    SOURCE_CLASS: ClassVar[str] = 'Order'
    kind: Literal["order"] = "order"
    project_id: ProjectId
    counterparty_id: Fact[PartyId] = Field(default_factory=unknown)
    document_ids: tuple[DocumentId, ...] = ()
    order_type: Fact[Literal["sales_order", "purchase_order", "change_order", "other"]] = Field(default_factory=unknown)
    contract_id: Fact[UUID] = Field(default_factory=unknown)
    source_order_identifier: Fact[Text] = Field(default_factory=unknown)
