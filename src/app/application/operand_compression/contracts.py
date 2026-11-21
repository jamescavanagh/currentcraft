"""Array-free application contracts for checked operand-field compression."""
from __future__ import annotations

import hashlib
from typing import Annotated, Literal

from pydantic import Field, StringConstraints, field_validator, model_validator

from app.application.common.contracts import _Frozen
from app.application.gauge.contracts import (EMBEDDINGS_SPEC, EmbeddingSpaceRef, GaugeCheckResult, GaugeNode,
                                             GaugeParams, GaugeRequest, GaugeResult)
from app.application.simulation.contracts import FrameId, NodeRole
from app.application.simulation.tensors import TensorRef
from app.domain.operand import DomainContext, OperandProfile

SCHEMA_VERSION = "datamesh-operand-compression/v1"
Digest = Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{64}$")]


class OperandCompressionRequest(_Frozen):
    """One caller-ordered embedding cloud, explicitly labeled with operand/domain context."""

    schema_version: Literal["datamesh-operand-compression/v1"] = SCHEMA_VERSION
    frame_id: FrameId = Field(description="Pinned frame identity for this candidate analysis.")
    space: EmbeddingSpaceRef = Field(description="Embedding model, version, and reduction provenance.")
    profiles: tuple[OperandProfile, ...] = Field(min_length=5, max_length=4096, description="Candidate domain profiles in embedding row order; each contains a thing operand, never a person or client party.")
    embeddings: TensorRef = Field(description="N x K float64 tensor reference; arrays stay in infrastructure.")
    params: GaugeParams = Field(default_factory=GaugeParams, description="Existing checked gauge-reduction parameters.")

    @field_validator("profiles")
    @classmethod
    def _unique_profiles(cls, profiles):
        ids = [profile.operand.object_id for profile in profiles]
        if len(ids) != len(set(ids)):
            raise ValueError("operand identities must be unique")
        profile_ids = [profile.profile_id for profile in profiles]
        if len(profile_ids) != len(set(profile_ids)):
            raise ValueError("profile identities must be unique")
        return profiles

    @model_validator(mode="after")
    def _tensor_alignment(self):
        if self.embeddings.spec != EMBEDDINGS_SPEC:
            raise ValueError("embeddings must use the existing EMBEDDINGS_SPEC")
        if self.embeddings.shape[0] != len(self.profiles):
            raise ValueError("embedding row count must equal the ordered profile count")
        if self.params.k >= len(self.profiles):
            raise ValueError("GaugeParams.k must be less than the profile count")
        return self

    def digest(self) -> str:
        return hashlib.sha256(self.model_dump_json().encode()).hexdigest()

    def as_gauge_request(self) -> GaugeRequest:
        """Adapt identities to the existing gauge port without embedding private labels in the result."""
        nodes = tuple(GaugeNode(id=str(profile.operand.object_id), role=NodeRole.OPERAND,
                                source_ref=str(profile.profile_id)) for profile in self.profiles)
        return GaugeRequest(frame_id=self.frame_id, space=self.space, nodes=nodes,
                            embeddings=self.embeddings, params=self.params)


class OperandCompressionResult(_Frozen):
    """Candidate result reusing gauge tensors and invariance receipt, with no policy/approval semantics."""

    schema_version: Literal["datamesh-operand-compression/v1"] = SCHEMA_VERSION
    request_digest: Digest = Field(description="Digest of the exact request.")
    result_kind: Literal["embedding_geometry"] = Field(default="embedding_geometry")
    candidate_only: Literal[True] = Field(default=True, description="Research result, not a forecast, fact, or release decision.")
    domain_contexts: tuple[DomainContext, ...] = Field(description="Contexts represented by the input operands.")
    profile_ids: tuple[str, ...] = Field(description="Candidate profile identity order of the input.")
    operand_ids: tuple[str, ...] = Field(description="Row identity order of the gauge result.")
    gauge_result: GaugeResult = Field(description="Existing gauge-invariant tensor readings and metadata.")
    invariance: GaugeCheckResult = Field(description="Existing invariance check for the same frame and request.")

    @model_validator(mode="after")
    def _checked_same_request(self):
        if not self.invariance.passed:
            raise ValueError("failed invariance results cannot be returned as compressed readings")
        if self.gauge_result.request_digest != self.invariance.request_digest:
            raise ValueError("gauge result and invariance receipt must describe the same request")
        if len(self.profile_ids) != len(self.operand_ids):
            raise ValueError("each compressed operand must have one profile identity")
        if self.gauge_result.node_ids != self.operand_ids:
            raise ValueError("operand order must equal the gauge result node order")
        if len(set(self.domain_contexts)) != len(self.domain_contexts):
            raise ValueError("domain contexts must be unique")
        return self


__all__ = ["OperandCompressionRequest", "OperandCompressionResult", "SCHEMA_VERSION"]
