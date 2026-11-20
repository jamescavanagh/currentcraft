"""Source reference to a project document; no implicit approval."""
from typing import ClassVar, Literal
from pydantic import Field
from app.domain.versioning import VersionedEntity
from app.domain.shared.facts import Fact, unknown
from app.domain.shared.identity import DocumentId, ProjectId, Text


class ReferenceDocument(VersionedEntity):
    """Contextual document reference; not a duplicate artifact."""

    SOURCE_CLASS: ClassVar[str] = 'ReferenceDocument'
    kind: Literal["reference_document"] = "reference_document"
    project_id: ProjectId
    document_id: DocumentId
    source_role: Fact[Text] = Field(default_factory=unknown)
