"""Immutable source-reported document revision; no inferred current revision."""
from typing import ClassVar, Literal, Annotated
from uuid import UUID
from pydantic import Field, StringConstraints, model_validator
from app.domain.versioning import VersionedEntity
from app.domain.shared.facts import Fact, unknown
from app.domain.shared.identity import DocumentId, ProjectId, Text

SHA256 = Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{64}$")]


class Revision(VersionedEntity):
    """Document version and optional artifact, separate from document identity."""

    SOURCE_CLASS: ClassVar[str] = 'Revision'
    kind: Literal["revision"] = "revision"
    project_id: ProjectId
    document_id: DocumentId
    source_revision_label: Fact[Text] = Field(default_factory=unknown)
    artifact_locator: Fact[Text] = Field(default_factory=unknown)
    content_sha256: Fact[SHA256] = Field(default_factory=unknown)
    supersedes_id: Fact[UUID] = Field(default_factory=unknown)

    @model_validator(mode="after")
    def distinct_predecessor(self):
        if self.supersedes_id.value == self.entity_id:
            raise ValueError("revision cannot supersede itself")
        return self
