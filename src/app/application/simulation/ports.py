"""Ports for the simulation use cases. Application code depends on these; infrastructure implements them.

No port signature mentions an array type: tensors cross the boundary only as ``TensorRef``.
"""

from __future__ import annotations

from typing import Mapping, Protocol, runtime_checkable

from .contracts import (BufferRingRequest, BufferRingResult, CnnSample, CnnSampleRequest, GraphSample,
                        GraphSampleRequest, NodeInteractionRequest, NodeInteractionResult, TransformSpec)
from .tensors import TensorRef


@runtime_checkable
class TensorStorePort(Protocol):
    """Resolves refs. Only infrastructure can read or write the underlying arrays."""

    def describe(self, key: str) -> TensorRef: ...
    def contains(self, ref: TensorRef) -> bool: ...
    def release(self, key: str) -> None: ...


@runtime_checkable
class TensorTransformPort(Protocol):
    """Tensor-to-tensor transforms (slice selection, normalisation, casting) run here, not in use cases."""

    def apply(self, spec: TransformSpec, source: TensorRef) -> TensorRef: ...


@runtime_checkable
class NodeInteractionPort(Protocol):
    def simulate(self, request: NodeInteractionRequest) -> NodeInteractionResult: ...


@runtime_checkable
class BufferRingPort(Protocol):
    def simulate(self, request: BufferRingRequest) -> BufferRingResult: ...


@runtime_checkable
class CnnSamplePort(Protocol):
    def build(self, request: CnnSampleRequest) -> CnnSample: ...


@runtime_checkable
class GraphTensorPort(Protocol):
    def build(self, request: GraphSampleRequest) -> GraphSample: ...


# --------------------------------------------------------------------------- planned (no adapter yet)

@runtime_checkable
class CnnEncoderPort(Protocol):
    """PLANNED. CNN-1 per slice -> CNN-2 along slices. Returns refs to motif maps and a frame embedding."""

    def encode(self, sample: CnnSample) -> Mapping[str, TensorRef]: ...


@runtime_checkable
class GnnEncoderPort(Protocol):
    """PLANNED. Message passing over GraphSample; may consume the CNN frame embedding as a graph-level input."""

    def encode(self, graph: GraphSample, frame_embedding: TensorRef | None = None) -> Mapping[str, TensorRef]: ...
