"""Ports for the HFGT capability graph. Application code depends on these; infrastructure implements them."""
from __future__ import annotations

from typing import Mapping, Protocol

from app.application.simulation.tensors import TensorRef

from .contracts import CapabilityGraphSample, HfgtGraphRequest


class HfgtGraphPort(Protocol):
    """Builds the capability graph: incidence, feasible sequences, features. Arrays stay in infrastructure."""

    def build(self, request: HfgtGraphRequest) -> CapabilityGraphSample: ...


class CapabilityGnnEncoderPort(Protocol):
    """Relational GNN over edge_type, messages both ways. Declared in 0.9.9; no implementation until 0.10.x."""

    def encode(self, sample: CapabilityGraphSample, content: TensorRef | None = None) -> Mapping[str, TensorRef]: ...
