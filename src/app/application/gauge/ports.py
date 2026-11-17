"""Gauge ports. No signature mentions an array type: tensors cross the boundary only as ``TensorRef``.

The tensor store is the simulation slice's ``TensorStorePort``: one store serves both slices.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from app.application.simulation.ports import TensorStorePort  # noqa: F401  (re-exported: shared store)

from .contracts import GaugeCheckRequest, GaugeCheckResult, GaugeRequest, GaugeResult, StageNullRequest, StageNullResult


@runtime_checkable
class GaugeReductionPort(Protocol):
    """Embeddings -> frames, director, connection (vector potential) and gauge-invariant operand properties."""

    def reduce(self, request: GaugeRequest) -> GaugeResult: ...


@runtime_checkable
class GaugeInvariancePort(Protocol):
    """Re-run a reduction under gauge and symmetry transformations; every invariant must be unchanged."""

    def check(self, request: GaugeCheckRequest) -> GaugeCheckResult: ...


@runtime_checkable
class ParticipationNullPort(Protocol):
    """Stage-preserving curveball null plus a paired, stage-stratified bootstrap of local vs global AUC."""

    def test(self, request: StageNullRequest) -> StageNullResult: ...
