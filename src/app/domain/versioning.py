"""Immutable entity capture. Persistence owns CAS history, not constructors."""
from typing import ClassVar, Literal
from uuid import UUID
from pydantic import ConfigDict, Field, model_validator
from app.domain.shared.scaffold_record import ScaffoldRecord
from app.domain.shared.identity import EvidenceId, ExternalReference


class VersionedEntity(ScaffoldRecord):
    """Implemented proposal, never an approved operating policy."""
    SOURCE_CLASS: ClassVar[str] = 'VersionedEntity'
    model_config = ConfigDict(frozen=True, extra="forbid", validate_default=True)
    SCHEMA_STATUS: ClassVar[str] = "v1-proposal"
    NOTE: ClassVar[str] = "Implemented capture; semantics require review. See V1_DOMAIN.md."
    entity_id: UUID = Field(description="Required opaque internal identity.")
    definition_status: Literal["v1-proposal"] = "v1-proposal"
    schema_version: Literal["enterprise-v1"] = "enterprise-v1"
    record_version: int = Field(default=1, ge=1, strict=True)
    external_refs: tuple[ExternalReference, ...] = ()
    evidence_ids: tuple[EvidenceId, ...] = ()

    @model_validator(mode="after")
    def unique_references(self):
        keys = [(r.namespace, r.key) for r in self.external_refs]
        if len(set(keys)) != len(keys) or len(set(self.evidence_ids)) != len(self.evidence_ids):
            raise ValueError("duplicate external or evidence reference")
        return self

    def require_accepted_definition(self) -> None:
        raise NotImplementedError(f"{type(self).__name__}: V1 proposal has not received semantic acceptance")
