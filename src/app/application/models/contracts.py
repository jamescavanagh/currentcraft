"""Synthetic capture contracts. Design: docs/pipelines/MODELS_EVIDENCE.md."""
from __future__ import annotations

import hashlib
import json
from datetime import datetime
from typing import Literal, Optional

from pydantic import Field, field_validator, model_validator

from app.application.common.contracts import _Frozen
from app.application.phase.contracts import Ident, RevisionRef, Digest, Version, PhaseReading, PhaseRevision

SCHEMA_VERSION = "currentcraft-models/v1"
Surface = Literal["body", "cells", "comments", "hidden_sheets", "properties",
                  "headers", "keys", "sheet_names", "links", "embedded_objects"]
Split = Literal["train", "validation", "test", "excluded"]


def _aware(value):
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("aware timestamp required")
    return value


def _unique(values):
    if len(values) != len(set(values)):
        raise ValueError("duplicate reference or code")
    return values


def _digest(record):
    """All declared fields, including identity and provenance; not just payload bytes."""
    payload = json.dumps(record.model_dump(mode="json"), sort_keys=True,
                         separators=(",", ":"), ensure_ascii=True, allow_nan=False)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


class ConfigurationArtifactRevision(_Frozen):
    """Exact synthetic capture; never proof of deployment or authorization."""
    schema_version: Literal["currentcraft-models/v1"] = Field(default=SCHEMA_VERSION, description="Contract version.")
    artifact_id: Ident = Field(description="Stable opaque artifact identity.")
    revision_id: Ident = Field(description="Exact opaque capture revision.")
    content_digest: Digest = Field(description="SHA-256 of exact captured bytes; not semantic equivalence.")
    payload_ref: Ident = Field(description="Opaque controlled-storage reference, never a source path.")
    product_instance_id: Ident = Field(description="Explicit instance binding, never inferred from a filename.")
    applicability_profile_ref: RevisionRef = Field(description="Exact declared applicability profile; validity checked separately.")
    source_id: Ident = Field(description="Opaque capture-source identity.")
    source_version: Optional[Version] = Field(description="Source revision if known; null is not an inferred date.")
    source_version_unknown_reason: Optional[Literal["not_recorded", "not_exposed", "not_authorized", "unavailable"]] = Field(
        default=None, description="Required exactly when source version is unknown.")
    captured_at: datetime = Field(description="Aware capture time; not deployment or effective event time.")
    capture_method: Version = Field(description="Versioned capture method.")
    epistemic_status: Literal["synthetic"] = Field(default="synthetic", description="Synthetic fixtures only.")

    @property
    def ref(self):
        return f"{self.artifact_id}@{self.revision_id}"

    @field_validator("captured_at")
    @classmethod
    def _time(cls, v):
        return _aware(v)

    @model_validator(mode="after")
    def _version_reason(self):
        if (self.source_version is None) != (self.source_version_unknown_reason is not None):
            raise ValueError("source version and unknown reason disagree")
        return self

    def fingerprint(self):
        return _digest(self)


class DatasetManifest(_Frozen):
    """Exact synthetic dataset recipe; does not authorize training."""
    schema_version: Literal["currentcraft-models/v1"] = Field(default=SCHEMA_VERSION, description="Contract version.")
    manifest_id: Ident = Field(description="Opaque dataset manifest identity.")
    revision_id: Ident = Field(description="Exact manifest revision.")
    input_refs: tuple[RevisionRef, ...] = Field(min_length=1, max_length=10000, description="Unique ordered exact input revisions.")
    input_digests: tuple[Digest, ...] = Field(min_length=1, max_length=10000, description="Exact byte digests aligned with input refs.")
    mapping_digest: Digest = Field(description="Source translation mapping digest.")
    config_digest: Digest = Field(description="Dataset build configuration digest.")
    method: Version = Field(description="Dataset building method and version.")
    split_policy_ref: RevisionRef = Field(description="Exact split policy; group independence checked externally.")
    split_assignments: tuple[tuple[RevisionRef, Split], ...] = Field(
        min_length=1, max_length=10000, description="Exactly one partition per input, in input order.")
    feature_spec_ref: RevisionRef = Field(description="Exact feature specification.")
    label_spec_ref: RevisionRef = Field(description="Separate exact label specification; separation alone is not leak prevention.")
    run_ref: Ident = Field(description="Build-run identity.")
    created_at: datetime = Field(description="Aware manifest creation time.")
    epistemic_status: Literal["synthetic"] = Field(default="synthetic", description="Synthetic fixtures only.")

    @property
    def ref(self):
        return f"{self.manifest_id}@{self.revision_id}"

    @field_validator("created_at")
    @classmethod
    def _time(cls, v):
        return _aware(v)

    @model_validator(mode="after")
    def _inputs(self):
        _unique(self.input_refs)
        if len(self.input_refs) != len(self.input_digests):
            raise ValueError("input digest alignment mismatch")
        if tuple(ref for ref, _ in self.split_assignments) != self.input_refs:
            raise ValueError("split assignments must cover each input once in order")
        if self.feature_spec_ref == self.label_spec_ref:
            raise ValueError("feature and label specifications must be distinct")
        return self

    def fingerprint(self):
        return _digest(self)


class SanitizationAssessment(_Frozen):
    """Technical synthetic assessment. Processed never means approved or safe."""
    schema_version: Literal["currentcraft-models/v1"] = Field(default=SCHEMA_VERSION, description="Contract version.")
    assessment_id: Ident = Field(description="Opaque assessment identity.")
    revision_id: Ident = Field(description="Exact assessment revision.")
    input_ref: RevisionRef = Field(description="Exact input artifact revision.")
    input_digest: Digest = Field(description="Exact input content digest.")
    output_ref: Optional[RevisionRef] = Field(default=None, description="Optional restricted output revision.")
    output_digest: Optional[Digest] = Field(default=None, description="Paired output content digest.")
    tool_version: Version = Field(description="Executed tool version, not a capability assertion.")
    rules_version: Version = Field(description="Executed rules version.")
    mapping_digest: Digest = Field(description="Replacement/identity mapping specification digest.")
    config_digest: Digest = Field(description="Executed assessment configuration digest.")
    method: Version = Field(description="Assessment method and version.")
    coverage_profile_ref: RevisionRef = Field(description="Exact coverage profile to resolve independently.")
    required_surfaces: tuple[Surface, ...] = Field(min_length=1, description="Declared required surfaces; profile agreement checked externally.")
    inspected_surfaces: tuple[Surface, ...] = Field(default=(), description="Declared inspected surfaces; not proof of execution.")
    unresolved_surfaces: tuple[Surface, ...] = Field(default=(), description="Uninspected or unresolved surfaces.")
    findings_ref: Ident = Field(description="Opaque detailed-findings reference, never source excerpts.")
    outcome: Literal["processed", "blocked", "review_required"] = Field(description="Technical result, not evidence validity or approval.")
    limitation_codes: tuple[Ident, ...] = Field(default=(), description="Controlled limitations, not raw errors.")
    run_ref: Ident = Field(description="Assessment execution identity, distinct from reading production.")
    assessed_at: datetime = Field(description="Aware assessment time.")
    epistemic_status: Literal["synthetic"] = Field(default="synthetic", description="Synthetic fixtures only.")

    @property
    def ref(self):
        return f"{self.assessment_id}@{self.revision_id}"

    @field_validator("assessed_at")
    @classmethod
    def _time(cls, v):
        return _aware(v)

    @model_validator(mode="after")
    def _coverage(self):
        for items in (self.required_surfaces, self.inspected_surfaces, self.unresolved_surfaces, self.limitation_codes):
            _unique(items)
        if (self.output_ref is None) != (self.output_digest is None):
            raise ValueError("output reference and digest must be paired")
        missing = set(self.required_surfaces) - set(self.inspected_surfaces)
        if not missing <= set(self.unresolved_surfaces):
            raise ValueError("missing required surfaces must be explicitly unresolved")
        if self.outcome == "processed":
            if self.output_ref is None or missing or self.unresolved_surfaces:
                raise ValueError("processed requires output and complete declared coverage")
        if self.outcome == "blocked" and self.output_ref is not None:
            raise ValueError("blocked cannot carry usable output")
        if self.outcome != "processed" and not self.limitation_codes:
            raise ValueError("nonprocessed assessment requires a limitation code")
        return self

    def fingerprint(self):
        return _digest(self)


def _artifacts(records):
    result = {}
    for record in records:
        if not isinstance(record, ConfigurationArtifactRevision):
            raise ValueError("wrong artifact record type")
        if record.ref in result:
            raise ValueError("duplicate supplied artifact revision")
        result[record.ref] = record
    return result


def _check_digest(records, ref, digest):
    if ref not in records or records[ref].content_digest != digest:
        raise ValueError("artifact reference or digest mismatch")


def check_dataset_artifacts(manifest: DatasetManifest, artifacts: tuple[ConfigurationArtifactRevision, ...]) -> None:
    """Check supplied records, not storage authenticity or feature/label leakage."""
    records = _artifacts(artifacts)
    for ref, digest in zip(manifest.input_refs, manifest.input_digests):
        _check_digest(records, ref, digest)


def check_assessment_artifacts(assessment: SanitizationAssessment, artifacts: tuple[ConfigurationArtifactRevision, ...]) -> None:
    """Check exact input/output declarations, not the content's safety."""
    records = _artifacts(artifacts)
    _check_digest(records, assessment.input_ref, assessment.input_digest)
    if assessment.output_ref is not None:
        _check_digest(records, assessment.output_ref, assessment.output_digest)


def check_phase_assessment(reading: PhaseReading, assessment: SanitizationAssessment, phase: PhaseRevision) -> None:
    """Pure check of resolved typed records. Does not promote validity or authorize a phase."""
    if not isinstance(reading, PhaseReading) or not isinstance(assessment, SanitizationAssessment) or not isinstance(phase, PhaseRevision):
        raise ValueError("wrong association record type")
    if reading.phase_ref != phase.ref:
        raise ValueError("phase revision mismatch")
    if (reading.source_id, reading.source_version) != (assessment.assessment_id, assessment.revision_id):
        raise ValueError("assessment source revision mismatch")
    if reading.mapping_digest != assessment.mapping_digest or reading.config_digest != assessment.config_digest:
        raise ValueError("assessment provenance mismatch")


CONTRACTS = (ConfigurationArtifactRevision, DatasetManifest, SanitizationAssessment)
