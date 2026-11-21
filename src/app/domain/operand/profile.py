"""Six-domain references, not replacement aggregates. Design: OPERAND_COMPRESSION.md."""
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, PositiveInt, model_validator

DomainContext = Literal["projects", "working_docs", "commercial_orders", "subsystems",
                        "site_acceptance_testing", "feature_compatibility"]
ThingKind = Literal["project", "document", "order", "subsystem", "test_record", "feature_configuration"]
LinkKind = Literal["selects_baseline", "evidences_configuration", "requests_configuration",
                   "maps_configuration", "tests_configuration", "defines_configuration"]
CONTEXT_KINDS = dict(zip(DomainContext.__args__, ThingKind.__args__))
CONTEXT_LINKS = dict(zip(DomainContext.__args__, LinkKind.__args__))


class FrozenValue(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", validate_default=True)


class OperandRef(FrozenValue):
    """Opaque reference to an existing thing at an exact record revision."""
    object_id: UUID = Field(description="Existing opaque thing ID; never a person, resource or party.")
    object_kind: ThingKind = Field(description="Thing kind matching the explicit domain context.")
    domain_context: DomainContext = Field(description="One of the six scoped contexts, not a universal ontology.")
    record_version: PositiveInt = Field(description="Exact source entity record version; no identity regeneration.")

    @model_validator(mode="after")
    def matching_context(self):
        if CONTEXT_KINDS[self.domain_context] != self.object_kind:
            raise ValueError("thing kind does not match domain context")
        return self


class ConfigurationLink(FrozenValue):
    """Sourced, context-specific assertion; never an automatic state transition."""
    configuration_id: UUID = Field(description="Opaque identity of the selected/requested/evidenced configuration.")
    graph_id: UUID = Field(description="Exact feature-model graph identity.")
    graph_revision: PositiveInt = Field(description="Exact feature-model graph revision.")
    predicate: LinkKind = Field(description="Context-specific assertion, not compatibility or release authority.")
    evidence_ids: tuple[UUID, ...] = Field(min_length=1, description="Opaque supporting evidence references resolved privately.")

    @model_validator(mode="after")
    def unique_evidence(self):
        if len(set(self.evidence_ids)) != len(self.evidence_ids):
            raise ValueError("duplicate link evidence")
        object.__setattr__(self, "evidence_ids", tuple(sorted(self.evidence_ids)))
        return self


class OperandProfile(FrozenValue):
    """Candidate view of one existing thing; geometry and source records stay separate."""
    profile_id: UUID = Field(description="Opaque identity of this candidate profile.")
    operand: OperandRef = Field(description="Existing entity reference with exact version.")
    projection_ref: UUID = Field(description="Opaque caller-supplied versioned projection reference.")
    configuration_link: ConfigurationLink | None = Field(default=None, description="Optional sourced link; absence asserts no configuration fact.")
    interpretation_status: Literal["candidate"] = Field(default="candidate", description="No accepted policy or operational authority.")

    @model_validator(mode="after")
    def matching_link(self):
        if self.configuration_link and self.configuration_link.predicate != CONTEXT_LINKS[self.operand.domain_context]:
            raise ValueError("configuration predicate does not match domain context")
        return self


CONTRACTS = (OperandRef, ConfigurationLink, OperandProfile)
