"""V1 capture proposal. Design: docs/domain/NEEDS_AND_SCOPE.md."""
from typing import ClassVar, Literal
from pydantic import Field
from app.domain.versioning import VersionedEntity
from app.domain.shared.facts import Fact, unknown
from app.domain.shared.identity import DocumentId, ProjectId, Text

ScopeCategory = Literal["internal_labor", "outsourced_labor", "vendor_service"]


class Scope(VersionedEntity):
    """Labor or service scope stated in a document; separate from BOM materials. Not priced, approved or contracted."""
    SOURCE_CLASS: ClassVar[str] = '(addition)'
    kind: Literal["scope"] = "scope"
    project_id: ProjectId = Field(description="Project the scope belongs to.")
    document_id: Fact[DocumentId] = Field(default_factory=unknown, description="Document that states this scope, or an explicit unknown.")
    category: Fact[ScopeCategory] = Field(default_factory=unknown, description="internal_labor, outsourced_labor or vendor_service; never mixed with materials.")
    statement: Fact[Text] = Field(default_factory=unknown, description="Evidenced scope statement, or an explicit unknown.")
