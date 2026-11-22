"""Explicit canonical reference resolution for six-type extensions.

Kind, exact version and ownership are established here, never assumed by the domain. Which ownership
relations exist, and which are required, comes from an ownership profile pinned to the domain's
referenced standard (its primary framework profile). Real profiles are private REF data loaded by an
infrastructure adapter; public code and fixtures stay synthetic. Resolution grants no authority.
"""
from datetime import datetime
from typing import Annotated, Literal, Protocol
from uuid import UUID

from pydantic import AfterValidator, Field, StringConstraints, model_validator

from app.application.common.contracts import _Frozen
from app.domain.operand.types import CanonicalKind, CanonicalRef, ExtensionRecord, ReferenceUse, context_kind

Digest = Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{64}$")]
Code = Annotated[str, StringConstraints(strict=True, pattern=r"^[A-Za-z0-9._:-]{1,120}$")]
# Owner fields an adapter may read from a canonical record. A profile naming anything else is rejected.
OwnerField = Literal["project_id", "document_id", "system_id", "phase_id", "parent_wbs_id",
                     "product_definition_id", "contract_id", "reference_set_id"]


def _aware(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("timestamp must be timezone-aware")
    return value


Aware = Annotated[datetime, AfterValidator(_aware)]


class StandardPin(_Frozen):
    """The referenced standard an ownership profile is drawn from: its framework profile, exactly."""
    framework_id: Code = Field(description="Opaque framework identity; real identities stay private.")
    framework_edition: Code = Field(description="Exact framework edition.")
    profile_version: Code = Field(description="Exact framework-profile version the rules are drawn from.")
    source_digest: Digest = Field(description="SHA-256 of the private source the profile was built from.")


class OwnershipRule(_Frozen):
    """One ownership relation the referenced standard defines: a subject kind is owned via one field."""
    rule_id: Code = Field(description="Opaque rule identity, stable across profile versions.")
    concept_id: Code = Field(description="Framework concept this relation is drawn from.")
    subject_kind: CanonicalKind = Field(description="Canonical kind that is owned.")
    owner_kind: CanonicalKind = Field(description="Canonical kind that owns it.")
    via: OwnerField = Field(description="Allowlisted canonical owner field holding the owner identity.")
    required: bool = Field(description="When true, an unknown owner leaves the reference unverified.")


class OwnershipProfile(_Frozen):
    """Versioned ownership rules for canonical kinds, pinned to one referenced standard."""
    schema_: Literal["framework-ownership/0"] = Field(alias="schema", description="Dedicated ownership schema, separate from framework-profile/0.")
    standard: StandardPin = Field(description="Exact referenced standard the rules come from.")
    ownership_version: Code = Field(description="Version of this ownership mapping, not of the standard.")
    valid_from: Aware = Field(description="Start of validity, timezone-aware.")
    valid_to: Aware | None = Field(default=None, description="End of validity, or open.")
    roots: tuple[CanonicalKind, ...] = Field(min_length=1, description="Kinds that own others and are owned by nothing.")
    rules: tuple[OwnershipRule, ...] = Field(min_length=1, description="Ownership relations; unlisted kinds stay unverified.")

    model_config = {"populate_by_name": True}

    @model_validator(mode="after")
    def closed_rules(self):
        if self.valid_to is not None and self.valid_to <= self.valid_from:
            raise ValueError("ownership validity window is empty")
        if len({r.rule_id for r in self.rules}) != len(self.rules):
            raise ValueError("duplicate ownership rule")
        pairs = [(r.subject_kind, r.via) for r in self.rules]
        if len(set(pairs)) != len(pairs):
            raise ValueError("conflicting ownership rules for one field")
        if set(self.roots) & {r.subject_kind for r in self.rules}:
            raise ValueError("a root kind cannot be owned")
        if len(set(self.roots)) != len(self.roots):
            raise ValueError("duplicate root kind")
        return self

    def rules_for(self, kind: str) -> tuple[OwnershipRule, ...]:
        return tuple(r for r in self.rules if r.subject_kind == kind)

    def valid_at(self, moment: datetime) -> bool:
        _aware(moment)
        return self.valid_from <= moment and (self.valid_to is None or moment < self.valid_to)


class OwnerFact(_Frozen):
    """An owner identity as the canonical record states it, or an explicit unknown."""
    via: OwnerField = Field(description="Canonical owner field read.")
    identity: UUID | None = Field(description="Owner identity, or null when the canonical record does not know it.")


class CanonicalLookup(_Frozen):
    """What the canonical store says about one exact reference. No reference is trusted without it."""
    status: Literal["found", "not_found", "version_absent", "access_denied"] = Field(description="Lookup outcome for the exact identity and version.")
    kind: CanonicalKind | None = Field(default=None, description="Stored kind, present only when found.")
    identity: UUID | None = Field(default=None, description="Stored identity, present only when found.")
    version: int | None = Field(default=None, ge=1, description="Stored record version, present only when found.")
    record_digest: Digest | None = Field(default=None, description="Digest of the exact stored canonical record.")
    owners: tuple[OwnerFact, ...] = Field(default=(), description="Owner facts read from allowlisted canonical fields.")

    @model_validator(mode="after")
    def shape(self):
        found = self.status == "found"
        values = (self.kind, self.identity, self.version, self.record_digest)
        if (found and any(v is None for v in values)) or (not found and any(v is not None for v in values)):
            raise ValueError("found lookups carry kind, identity, version and digest; others carry none")
        if not found and self.owners:
            raise ValueError("only found lookups carry owner facts")
        return self


class CanonicalReferencePort(Protocol):
    """Explicit port to the canonical store. One instance serves one authorized scope."""

    def lookup(self, reference: CanonicalRef) -> CanonicalLookup: ...


Finding = Literal[
    "verified", "unresolved_candidate", "required_not_found", "version_absent", "access_denied",
    "kind_mismatch", "identity_or_version_mismatch", "project_owner_mismatch", "owner_mismatch",
    "owner_unknown", "ownership_rule_absent", "ownership_context_absent",
]
BLOCKING = frozenset({"required_not_found", "version_absent", "access_denied", "kind_mismatch",
                      "identity_or_version_mismatch", "project_owner_mismatch", "owner_mismatch"})


class ReferenceFinding(_Frozen):
    """Resolution outcome for one reference use. Codes only: no labels or source text."""
    extension: CanonicalKind = Field(description="Six-domain context kind of the extension holding the reference.")
    role: str = Field(description="Field path of the reference inside the extension.")
    reference: CanonicalRef = Field(description="The exact reference checked.")
    findings: tuple[Finding, ...] = Field(min_length=1, description="Sorted outcome codes; 'verified' only when nothing else applies.")
    record_digest: Digest | None = Field(default=None, description="Digest of the resolved canonical record, when found.")
    rules_applied: tuple[Code, ...] = Field(default=(), description="Ownership rules from the referenced standard that were checked.")


class ResolutionReport(_Frozen):
    """Whether every canonical reference is real, exact and correctly owned under one pinned standard."""
    schema_version: Literal["currentcraft-reference-resolution/v1"] = Field(default="currentcraft-reference-resolution/v1", description="Resolution receipt family.")
    standard: StandardPin = Field(description="Referenced standard whose ownership rules were applied.")
    ownership_version: Code = Field(description="Ownership mapping version applied.")
    resolved_at: Aware = Field(description="Time the resolution ran; the profile must be valid then.")
    outcome: Literal["canonically_verified", "unverified", "blocked"] = Field(description="Blocked on any mismatch or missing required record; verified only when every reference is.")
    references: tuple[ReferenceFinding, ...] = Field(description="Per-reference findings in extension order.")
    grants_authority: Literal[False] = Field(default=False, description="Resolution establishes identity and ownership facts only, never approval.")


def _check(use: ReferenceUse, context: dict, lookup: CanonicalLookup, profile: OwnershipProfile):
    ref, findings, applied = use.reference, set(), []
    if lookup.status != "found":
        if lookup.status == "not_found":
            findings.add("required_not_found" if use.required else "unresolved_candidate")
        else:
            findings.add(lookup.status)
        return findings, applied
    if lookup.kind != ref.kind:
        findings.add("kind_mismatch")
    if (lookup.identity, lookup.version) != (ref.identity, ref.version):
        findings.add("identity_or_version_mismatch")
    if ref.kind in profile.roots:
        if ref.kind == "project" and use.same_project and ref.identity != context["project"].identity:
            findings.add("project_owner_mismatch")
        return findings, applied
    rules = profile.rules_for(ref.kind)
    if not rules:
        findings.add("ownership_rule_absent")
        return findings, applied
    owners = {fact.via: fact.identity for fact in lookup.owners}
    for rule in rules:
        applied.append(rule.rule_id)
        owner = owners.get(rule.via)
        if owner is None:
            if rule.required:
                findings.add("owner_unknown")
            continue
        if rule.owner_kind == "project":
            if use.same_project and owner != context["project"].identity:
                findings.add("project_owner_mismatch")
        elif use.expect_owner == "subject":
            subject = context.get("subject")
            if subject is None or subject.kind != rule.owner_kind:
                findings.add("ownership_context_absent")
            elif owner != subject.identity:
                findings.add("owner_mismatch")
    return findings, applied


def resolve_extensions(extensions: tuple[ExtensionRecord, ...], port: CanonicalReferencePort,
                       profile: OwnershipProfile, resolved_at: datetime) -> ResolutionReport:
    """Resolve every canonical reference held by the given extensions through one explicit port."""
    if not profile.valid_at(resolved_at):
        raise ValueError("ownership profile is not valid at the resolution time")
    results, worst = [], "canonically_verified"
    for extension in extensions:
        context = {"project": extension.project, "subject": getattr(extension, "subject", None)}
        for use in extension.references():
            lookup = port.lookup(use.reference)
            if not isinstance(lookup, CanonicalLookup):
                raise TypeError("port must return a CanonicalLookup")
            findings, applied = _check(use, context, lookup, profile)
            codes = tuple(sorted(findings)) or ("verified",)
            if BLOCKING & set(codes):
                worst = "blocked"
            elif codes != ("verified",) and worst != "blocked":
                worst = "unverified"
            results.append(ReferenceFinding(extension=context_kind(extension), role=use.role, reference=use.reference,
                findings=codes, record_digest=lookup.record_digest, rules_applied=tuple(applied)))
    return ResolutionReport(standard=profile.standard, ownership_version=profile.ownership_version,
        resolved_at=resolved_at, outcome=worst, references=tuple(results))


CONTRACTS = (StandardPin, OwnershipRule, OwnershipProfile, OwnerFact, CanonicalLookup, ReferenceFinding, ResolutionReport)
