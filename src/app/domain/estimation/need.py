"""V1 capture proposal. Design: docs/domain/NEEDS_AND_SCOPE.md."""
from typing import ClassVar, Literal
from pydantic import Field, model_validator
from app.domain.versioning import VersionedEntity
from app.domain.shared.facts import Fact, unknown
from app.domain.shared.identity import DocumentId, ProjectId, Text


class Need(VersionedEntity):
    """A stated project need; capture only, never an estimate, commitment or approved scope."""
    SOURCE_CLASS: ClassVar[str] = '(addition)'
    kind: Literal["need"] = "need"
    project_id: ProjectId = Field(description="Project the need was stated for.")
    statement: Fact[Text] = Field(default_factory=unknown, description="Evidenced statement of the need, or an explicit unknown.")
    document_ids: tuple[DocumentId, ...] = Field(default=(), description="Documents explicitly recorded as stating this need's scope; never inferred.")

    @model_validator(mode="after")
    def unique_documents(self):
        if len(set(self.document_ids)) != len(self.document_ids):
            raise ValueError("duplicate document reference")
        return self
