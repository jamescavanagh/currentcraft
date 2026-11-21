"""Optional geometry consumer; feature semantics live in the feature graph."""
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

SCHEMA_VERSION = "datamesh-operand-compression/v2"
Digest = Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{64}$")]


class OperandCompressionRequest(_Frozen):
    """Caller-ordered embedding cloud; cannot derive or validate domain facts."""
    schema_version: Literal["datamesh-operand-compression/v2"] = Field(default=SCHEMA_VERSION, description="Six-domain profile shape; old soil-profile v1 is rejected.")
    frame_id: FrameId = Field(description="Pinned frame identity for candidate geometry.")
    space: EmbeddingSpaceRef = Field(description="Embedding model, version and reduction provenance.")
    profiles: tuple[OperandProfile, ...] = Field(min_length=5, max_length=4096, description="Six-domain references in explicit embedding row order.")
    embeddings: TensorRef = Field(description="N x K float64 descriptor; arrays stay in infrastructure.")
    params: GaugeParams = Field(default_factory=GaugeParams, description="Existing checked gauge parameters.")

    @field_validator("profiles")
    @classmethod
    def unique_profiles(cls, profiles):
        for values in ([p.operand.object_id for p in profiles], [p.profile_id for p in profiles]):
            if len(values) != len(set(values)):
                raise ValueError("operand and profile identities must be unique")
        return profiles

    @model_validator(mode="after")
    def tensor_alignment(self):
        if self.embeddings.spec != EMBEDDINGS_SPEC:
            raise ValueError("embeddings must use EMBEDDINGS_SPEC")
        if self.embeddings.shape[0] != len(self.profiles):
            raise ValueError("embedding rows must match ordered profiles")
        if self.params.k >= len(self.profiles):
            raise ValueError("k must be less than profile count")
        return self

    def digest(self) -> str:
        return hashlib.sha256(self.model_dump_json().encode()).hexdigest()

    def as_gauge_request(self) -> GaugeRequest:
        nodes = tuple(GaugeNode(id=str(p.operand.object_id), role=NodeRole.OPERAND, source_ref=str(p.profile_id)) for p in self.profiles)
        return GaugeRequest(frame_id=self.frame_id, space=self.space, nodes=nodes, embeddings=self.embeddings, params=self.params)


class OperandCompressionResult(_Frozen):
    """Checked geometry receipt, not feature compatibility or operational authority."""
    schema_version: Literal["datamesh-operand-compression/v2"] = Field(default=SCHEMA_VERSION, description="Independent geometry consumer contract family.")
    request_digest: Digest = Field(description="Exact input request digest.")
    result_kind: Literal["embedding_geometry"] = Field(default="embedding_geometry", description="Geometry, not physical or process meaning.")
    candidate_only: Literal[True] = Field(default=True, description="Never a release, forecast or confirmed relation.")
    domain_contexts: tuple[DomainContext, ...] = Field(description="Six-domain contexts represented in the input.")
    profile_ids: tuple[str, ...] = Field(description="Opaque profile identities in caller order.")
    operand_ids: tuple[str, ...] = Field(description="Opaque thing identities in gauge row order.")
    gauge_result: GaugeResult = Field(description="Existing gauge tensor descriptors and metadata.")
    invariance: GaugeCheckResult = Field(description="Existing checked invariance receipt for the same request.")

    @model_validator(mode="after")
    def checked_same_request(self):
        if not self.invariance.passed:
            raise ValueError("failed invariance cannot be returned")
        if self.gauge_result.request_digest != self.invariance.request_digest:
            raise ValueError("gauge result and receipt must describe the same request")
        if len(self.profile_ids) != len(self.operand_ids) or self.gauge_result.node_ids != self.operand_ids:
            raise ValueError("profile and operand order must match gauge rows")
        if len(set(self.domain_contexts)) != len(self.domain_contexts):
            raise ValueError("domain contexts must be unique")
        return self


CONTRACTS = (OperandCompressionRequest, OperandCompressionResult)
__all__ = ["OperandCompressionRequest", "OperandCompressionResult", "CONTRACTS", "SCHEMA_VERSION"]
