"""V1 capture proposal. Sources, invariants and open decisions: docs/domain/V1_DOMAIN.md."""
from typing import ClassVar, Literal
from pydantic import Field
from app.domain.versioning import VersionedEntity
from app.domain.shared.facts import Fact, unknown
from app.domain.shared.identity import Text, ProjectId


class Document(VersionedEntity):
    """Versioned document identity; lifecycle policy is unresolved."""
    SOURCE_CLASS: ClassVar[str] = 'Document'
    kind: Literal["document"] = "document"
    project_id: ProjectId
    name: Fact[Text] = Field(default_factory=unknown)
    source_version: Fact[Text] = Field(default_factory=unknown)
    storage_locator: Fact[Text] = Field(default_factory=unknown)
    source_type_label: Fact[Text] = Field(default_factory=unknown)
    source_state: Fact[Text] = Field(default_factory=unknown)

    def transition(self, target: str):
        raise PermissionError("document lifecycle policy is not defined")
