"""Independent contract capture; design: docs/domain/P0_P3_CAPTURE.md."""
from typing import ClassVar, Literal
from pydantic import Field
from app.domain.versioning import VersionedEntity
from app.domain.shared.facts import Fact, unknown
from app.domain.shared.identity import ProjectId, PartyId, DocumentId, Text


class Contract(VersionedEntity):
    """Company-client agreement capture; counterparty classification is not verified here."""

    SOURCE_CLASS: ClassVar[str] = 'Contract'
    kind: Literal["contract"] = "contract"
    project_id: ProjectId
    counterparty_id: Fact[PartyId] = Field(default_factory=unknown)
    source_contract_identifier: Fact[Text] = Field(default_factory=unknown)
    scope_document_ids: tuple[DocumentId, ...] = ()
    execution_verified: Fact[bool] = Field(default_factory=unknown)
