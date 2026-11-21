"""Deterministic, array-free feature snapshots. Design: OPERAND_COMPRESSION.md."""
from datetime import datetime, timezone
import hashlib
from typing import Annotated, Literal
from uuid import UUID

from pydantic import AfterValidator, Field, PositiveInt, StringConstraints, model_validator

from .profile import FrozenValue

SCHEMA_VERSION = "currentcraft-feature-graph/v1"
ENCODING_VERSION = "mandatory-pairwise/v1"
Digest = Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{64}$")]


def utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("timezone-aware timestamp required")
    return value.astimezone(timezone.utc)


Timestamp = Annotated[datetime, AfterValidator(utc)]


def unique(values, label):
    if len(values) != len(set(values)):
        raise ValueError("duplicate " + label)
    return tuple(sorted(values))


class Provenance(FrozenValue):
    """Opaque evidence envelope; actual locators belong in authorized private storage."""
    evidence_id: UUID = Field(description="Opaque evidence assertion identity.")
    source_snapshot_id: UUID = Field(description="Exact opaque source snapshot/revision, not a raw locator.")
    captured_at: Timestamp = Field(description="When this evidence was captured, timezone-aware UTC.")
    method: Literal["source_assertion", "human_label"] = Field(description="Assertion method; neither option proves truth or authority.")


class FeatureDefinition(FrozenValue):
    """Stable feature identity with an independently versioned definition."""
    feature_id: UUID = Field(description="Stable opaque feature identity across definitions.")
    version: PositiveInt = Field(description="Definition version, independent of graph revision.")
    definition_digest: Digest = Field(description="SHA-256 of the exact private or synthetic definition.")
    status: Literal["active", "retired"] = Field(description="Explicit sourced definition status; omission is not retirement.")
    mandatory: bool = Field(description="Whether the active feature is required by this restricted model.")
    provenance: Provenance = Field(description="Evidence for this exact definition and status.")


class FeatureConstraint(FrozenValue):
    """Pairwise relation scoped to the enclosing exact graph revision."""
    constraint_id: UUID = Field(description="Opaque constraint identity within this graph revision.")
    kind: Literal["requires", "excludes"] = Field(description="Requires is directed; excludes forbids joint selection.")
    left: UUID = Field(description="Antecedent or first excluded feature, resolved at this graph revision.")
    right: UUID = Field(description="Required or second excluded feature, resolved at this graph revision.")
    provenance: Provenance = Field(description="Evidence for the relation, not mere co-presence.")

    @model_validator(mode="after")
    def distinct_endpoints(self):
        if self.left == self.right:
            raise ValueError("constraint endpoints must differ")
        return self


class ProductObservation(FrozenValue):
    """Exact product-revision observation, separate from model-permitted configurations."""
    observation_id: UUID = Field(description="Opaque observation identity.")
    product_id: UUID = Field(description="Opaque existing product identity, never a catalog number.")
    product_revision: PositiveInt = Field(description="Exact observed product/variant revision.")
    observed_at: Timestamp = Field(description="When the evidenced selection was observed.")
    present: tuple[UUID, ...] = Field(description="Features explicitly observed present.")
    absent: tuple[UUID, ...] = Field(default=(), description="Features explicitly observed absent; all other unlisted features are unknown.")
    complete: bool = Field(default=False, description="Explicit evidence of a complete selection, not installation, sale or acceptance.")
    provenance: Provenance = Field(description="Evidence for this exact product revision and selection.")

    @model_validator(mode="after")
    def consistent_selection(self):
        object.__setattr__(self, "present", unique(self.present, "present feature"))
        object.__setattr__(self, "absent", unique(self.absent, "absent feature"))
        if set(self.present) & set(self.absent):
            raise ValueError("present and absent observations conflict")
        if self.observed_at > self.provenance.captured_at:
            raise ValueError("observation cannot postdate capture")
        return self


class FeatureGraphRevision(FrozenValue):
    """Canonical immutable snapshot with effective and knowledge times."""
    schema_version: Literal["currentcraft-feature-graph/v1"] = Field(default=SCHEMA_VERSION, description="Independent feature-graph contract family.")
    encoding_version: Literal["mandatory-pairwise/v1"] = Field(default=ENCODING_VERSION, description="Limited constraint language, not full feature-model/SAT semantics.")
    graph_id: UUID = Field(description="Stable model graph identity.")
    revision: PositiveInt = Field(description="Sequential immutable graph revision.")
    valid_from: Timestamp = Field(description="Effective time of the complete snapshot.")
    recorded_at: Timestamp = Field(description="When this revision became known; no implicit clock.")
    features: tuple[FeatureDefinition, ...] = Field(min_length=1, description="Complete scoped feature definitions, canonicalized by ID.")
    constraints: tuple[FeatureConstraint, ...] = Field(default=(), description="Sourced constraints scoped to these exact feature definitions.")
    observations: tuple[ProductObservation, ...] = Field(default=(), description="Observed products, never inferred from allowed combinations.")

    @model_validator(mode="after")
    def consistent_snapshot(self):
        if self.valid_from > self.recorded_at:
            raise ValueError("prospective graph snapshots are outside this encoding")
        for field, key in (("features", "feature_id"), ("constraints", "constraint_id"), ("observations", "observation_id")):
            values = getattr(self, field)
            unique([getattr(value, key) for value in values], field + " identity")
            object.__setattr__(self, field, tuple(sorted(values, key=lambda value: getattr(value, key))))
        features = {f.feature_id: f for f in self.features}
        for item in (*self.features, *self.constraints, *self.observations):
            if item.provenance.captured_at > self.recorded_at:
                raise ValueError("snapshot cannot contain future evidence")
        for constraint in self.constraints:
            if any(key not in features or features[key].status != "active" for key in (constraint.left, constraint.right)):
                raise ValueError("constraint references missing or retired feature")
        for observation in self.observations:
            if set(observation.present + observation.absent) - features.keys():
                raise ValueError("observation references missing feature")
            if observation.observed_at > self.valid_from:
                raise ValueError("observation postdates effective snapshot")
        return self

    def digest(self) -> str:
        return hashlib.sha256(self.model_dump_json().encode()).hexdigest()


CONTRACTS = (Provenance, FeatureDefinition, FeatureConstraint, ProductObservation, FeatureGraphRevision)
