"""Array-free requests and receipts for candidate feature-graph analysis."""
import hashlib
from typing import Literal
from uuid import UUID

from pydantic import Field, PositiveInt, model_validator

from app.application.common.contracts import _Frozen
from app.domain.operand.feature_graph import Digest, ENCODING_VERSION, FeatureGraphRevision, Timestamp, unique

SCHEMA_VERSION = "currentcraft-feature-analysis/v1"


class ConfigurationRequest(_Frozen):
    """Selection pinned to one exact model, not a request to order/install/release."""
    schema_version: Literal["currentcraft-feature-analysis/v1"] = Field(default=SCHEMA_VERSION, description="Feature analysis request family.")
    configuration_id: UUID = Field(description="Opaque candidate configuration identity.")
    graph_id: UUID = Field(description="Selected graph identity.")
    graph_revision: PositiveInt = Field(description="Selected immutable graph revision.")
    graph_digest: Digest = Field(description="Exact graph content digest; mismatches fail closed.")
    selected: tuple[UUID, ...] = Field(description="Explicit feature assignment: listed true, all other model features false.")

    @model_validator(mode="after")
    def canonical_selection(self):
        object.__setattr__(self, "selected", unique(self.selected, "selected feature"))
        return self

    def digest(self) -> str:
        return hashlib.sha256(self.model_dump_json().encode()).hexdigest()


class ConfigurationResult(_Frozen):
    """Model outcome and source observation are independent of operational states."""
    schema_version: Literal["currentcraft-feature-analysis/v1"] = Field(default=SCHEMA_VERSION, description="Feature analysis result family.")
    configuration_id: UUID = Field(description="Candidate configuration evaluated.")
    graph_id: UUID = Field(description="Exact evaluated graph.")
    graph_revision: PositiveInt = Field(description="Exact evaluated graph revision.")
    graph_digest: Digest = Field(description="Exact evaluated graph content digest.")
    request_digest: Digest = Field(description="Exact canonical request digest.")
    encoding_version: Literal["mandatory-pairwise/v1"] = Field(default=ENCODING_VERSION, description="Only mandatory and pairwise requires/excludes checks.")
    model_outcome: Literal["allowed_by_model", "violates_model"] = Field(description="Validity under the limited selected encoding, not physical compatibility.")
    evidence_status: Literal["possible", "observed_configuration", "not_model_permitted"] = Field(description="Possible is allowed but unobserved; observation never grants authority.")
    violations: tuple[str, ...] = Field(description="Sorted deterministic violation codes; no private labels or exception text.")
    observation_ids: tuple[UUID, ...] = Field(description="Complete exact source observations, independently reported even if invalid.")
    candidate_only: Literal[True] = Field(default=True, description="No approval, order, installation, test pass or release authority.")

    @model_validator(mode="after")
    def consistent_receipt(self):
        if (self.model_outcome == "allowed_by_model") != (not self.violations):
            raise ValueError("model outcome and violation receipt disagree")
        expected = "observed_configuration" if self.observation_ids else (
            "possible" if self.model_outcome == "allowed_by_model" else "not_model_permitted")
        if self.evidence_status != expected:
            raise ValueError("evidence status and observation receipt disagree")
        unique(self.observation_ids, "observation receipt")
        if tuple(sorted(set(self.violations))) != self.violations:
            raise ValueError("violation receipt must be unique and sorted")
        return self


class AsOfRequest(_Frozen):
    """Two-clock historical query: no present-day leakage by default."""
    graph_id: UUID = Field(description="Graph to reconstruct.")
    effective_at: Timestamp = Field(description="Effective-time cutoff, timezone-aware.")
    known_at: Timestamp = Field(description="Knowledge/recorded-time cutoff, explicitly supplied.")


class FeatureGraphDiff(_Frozen):
    """Identity-level comparison, not causal inference or feature transfer evidence."""
    graph_id: UUID = Field(description="Shared graph identity.")
    before_revision: PositiveInt = Field(description="Earlier graph revision.")
    after_revision: PositiveInt = Field(description="Later graph revision.")
    before_digest: Digest = Field(description="Exact earlier snapshot digest.")
    after_digest: Digest = Field(description="Exact later snapshot digest.")
    introduced: tuple[UUID, ...] = Field(description="Newly listed features, not proof of first historical invention.")
    carried: tuple[UUID, ...] = Field(description="Identical definition carried into the later snapshot.")
    changed: tuple[UUID, ...] = Field(description="Changed retained definitions, excluding explicit retirement.")
    retired: tuple[UUID, ...] = Field(description="Previously active definitions explicitly retired.")
    no_longer_listed: tuple[UUID, ...] = Field(description="Missing IDs, not evidence of retirement or absence.")


CONTRACTS = (ConfigurationRequest, ConfigurationResult, AsOfRequest, FeatureGraphDiff)
