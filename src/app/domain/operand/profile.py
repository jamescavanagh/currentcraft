"""Candidate operand profiles inspired by pedology; deterministic and array-free."""
from __future__ import annotations

from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, NonNegativeInt, StringConstraints, model_validator

from app.domain.shared.facts import Fact, unknown
from app.domain.shared.identity import EvidenceId, Text

DomainContext = Literal[
    "projects",
    "inventory",
    "employees_contributors",
    "working_docs",
    "drawings",
    "subsystems",
    "product_features",
    "site_acceptance_testing",
    "commercial_orders",
    "clients",
    "estimation_needs_analysis",
]
ProfileLayerKind = Literal["pedogenic_horizon", "inherited_layer", "unknown"]
ProfileId = Annotated[str, StringConstraints(strict=True, min_length=1, max_length=120, pattern=r"\S")]

# These are resources, parties, or contextual relationships in Currentcraft, never operands.
_NON_OPERAND_KINDS = frozenset({
    "person", "employee", "contributor", "resource", "party", "client", "customer",
    "stakeholder", "consultant", "manufacturer_rep", "agent", "team",
})


class _Frozen(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", validate_default=True)


class OperandRef(_Frozen):
    """Reference to a thing operand; resource/party kinds are explicitly rejected."""

    object_id: UUID = Field(description="Opaque identity of the thing, never a person or party identity.")
    object_kind: Text = Field(description="Caller-owned thing-kind vocabulary; no kind mapping is inferred here.")
    domain_context: DomainContext = Field(description="One of the eleven declared Currentcraft contexts; timecards are excluded.")
    state: Fact[Text] = Field(default_factory=unknown, description="Evidence-backed state or explicit unknown; does not grant authority.")

    @model_validator(mode="after")
    def _thing_not_resource(self):
        normalized = self.object_kind.strip().casefold().replace(" ", "_").replace("-", "_")
        if normalized in _NON_OPERAND_KINDS:
            raise ValueError(f"{self.object_kind!r} is a resource/party kind, not an operand")
        return self


class ProfileLayer(_Frozen):
    """One captured profile stratum; source classification is not derived by the model."""

    layer_id: ProfileId = Field(description="Opaque layer identity within a profile.")
    order: NonNegativeInt = Field(description="Source-provided ordering; no physical thickness is inferred.")
    kind: ProfileLayerKind = Field(description="Candidate distinction: process-formed, inherited, or unresolved.")
    evidence_ids: tuple[EvidenceId, ...] = Field(default=(), description="Supporting source assertions when known.")

    @model_validator(mode="after")
    def _evidence_for_asserted_kind(self):
        if self.kind != "unknown" and not self.evidence_ids:
            raise ValueError("classified profile layers require supporting evidence")
        if len(set(self.evidence_ids)) != len(self.evidence_ids):
            raise ValueError("duplicate layer evidence IDs")
        return self


class FormationSet(_Frozen):
    """Candidate solum-like grouping of explicitly related process-formed layers."""

    period_ref: ProfileId = Field(description="Opaque, source-backed process-period reference.")
    layer_ids: tuple[ProfileId, ...] = Field(min_length=1, description="Explicit member layers; this class does not infer common formation.")
    evidence_ids: tuple[EvidenceId, ...] = Field(min_length=1, description="Evidence for the shared formation-period assertion.")

    @model_validator(mode="after")
    def _unique_members(self):
        if len(set(self.layer_ids)) != len(self.layer_ids) or len(set(self.evidence_ids)) != len(self.evidence_ids):
            raise ValueError("formation members and evidence IDs must be unique")
        return self


class OperandProfile(_Frozen):
    """Candidate profile view over one operand, distinct from its source object and numerical tensors."""

    profile_id: ProfileId = Field(description="Opaque profile identity.")
    operand: OperandRef = Field(description="Thing being represented; never an employee, contributor, or client party.")
    projection_ref: ProfileId = Field(description="Versioned projection/reference key supplied by the caller.")
    layers: tuple[ProfileLayer, ...] = Field(default=(), description="Captured layers; empty means none asserted, not none existing.")
    formation_sets: tuple[FormationSet, ...] = Field(default=(), description="Explicit source-supported groupings; candidate only.")
    interpretation_status: Literal["candidate"] = Field(default="candidate", description="Never approved policy or automatic authority.")

    @model_validator(mode="after")
    def _consistent_profile(self):
        ids = [layer.layer_id for layer in self.layers]
        orders = [layer.order for layer in self.layers]
        if len(ids) != len(set(ids)):
            raise ValueError("profile layer IDs must be unique")
        if len(orders) != len(set(orders)):
            raise ValueError("profile layer order values must be unique")
        known = {layer.layer_id: layer.kind for layer in self.layers}
        for group in self.formation_sets:
            missing = set(group.layer_ids) - set(known)
            if missing:
                raise ValueError(f"formation set references unknown layers: {sorted(missing)}")
            if any(known[layer_id] != "pedogenic_horizon" for layer_id in group.layer_ids):
                raise ValueError("formation sets may contain only explicitly classified process-formed layers")
        return self


__all__ = ["DomainContext", "FormationSet", "OperandProfile", "OperandRef", "ProfileLayer", "ProfileLayerKind"]
