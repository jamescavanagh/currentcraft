"""V1 capture proposal. Sources, invariants and open decisions: docs/domain/V1_DOMAIN.md."""
from typing import ClassVar, Literal
from pydantic import Field
from app.domain.versioning import VersionedEntity
from app.domain.shared.facts import Fact, unknown
from app.domain.shared.identity import ProjectId, PartyId, DocumentId


class Order(VersionedEntity):
    """Commercial order identity, separate from supporting documents."""
    SOURCE_CLASS: ClassVar[str] = 'Order'
    kind: Literal["order"] = "order"
    project_id: ProjectId
    counterparty_id: Fact[PartyId] = Field(default_factory=unknown)
    document_ids: tuple[DocumentId, ...] = ()
