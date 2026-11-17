"""Gauge use cases. Orchestrate ports, enforce cross-stage rules. No numpy, no adapters imported."""

from __future__ import annotations

from typing import Mapping, Optional

from app.application.simulation.contracts import InteractionNode, TensorContract
from app.application.simulation.ports import TensorStorePort
from app.application.simulation.tensors import TensorContractError

from .contracts import (FlowSide, GaugeCheckRequest, GaugeCheckResult, GaugeNode, GaugeRequest, GaugeResult,
                        StageNullRequest, StageNullResult)
from .ports import GaugeInvariancePort, GaugeReductionPort, ParticipationNullPort


def gauge_nodes_from_interactions(nodes: tuple[InteractionNode, ...],
                                  flows: Optional[Mapping[str, FlowSide]] = None) -> tuple[GaugeNode, ...]:
    """Carry simulation nodes (id, role, label, provenance) into the gauge slice. Embeddings still come from the store.

    >>> n = InteractionNode(id="v1", x=0.1, y=0.2, strength=-0.3, label="example-device")
    >>> g = gauge_nodes_from_interactions((n,), flows={"v1": FlowSide.DEMAND})[0]
    >>> (g.id, g.role.value, g.flow.value, g.label)
    ('v1', 'unassigned', 'demand', 'example-device')
    """
    flows = dict(flows or {})
    return tuple(GaugeNode(id=n.id, role=n.role, flow=flows.get(n.id, FlowSide.NEUTRAL), label=n.label,
                           source_ref=n.source_ref) for n in nodes)


class GaugeService:
    """Entry point for the gauge slice. ``reduce_checked`` refuses to return a reduction that fails invariance."""

    def __init__(self, store: TensorStorePort, reduction: GaugeReductionPort, invariance: GaugeInvariancePort,
                 nulls: ParticipationNullPort):
        self.store, self.reduction, self.invariance, self.nulls = store, reduction, invariance, nulls

    def _resolvable(self, contract: TensorContract) -> None:
        for name, ref in contract.tensor_refs().items():
            if ref is not None and not self.store.contains(ref):
                raise TensorContractError(f"{type(contract).__name__}.{name}: ref {ref.key} not in the tensor store")

    def reduce(self, request: GaugeRequest) -> GaugeResult:
        if not self.store.contains(request.embeddings):
            raise TensorContractError(f"embeddings ref {request.embeddings.key} not in the tensor store")
        result = self.reduction.reduce(request)
        if result.request_digest != request.digest():
            raise TensorContractError("reduction returned a result for a different request")
        if result.embeddings_sha256 != request.embeddings.sha256:
            raise TensorContractError("reduction read different embedding bytes than the request names")
        self._resolvable(result)
        return result

    def check(self, request: GaugeCheckRequest) -> GaugeCheckResult:
        if not self.store.contains(request.request.embeddings):
            raise TensorContractError("embeddings ref not in the tensor store")
        return self.invariance.check(request)

    def reduce_checked(self, request: GaugeRequest, seed: int = 0) -> tuple[GaugeResult, GaugeCheckResult]:
        """Protocol rule: no gauge reading is used unless the invariance battery passes on the same request."""
        check = self.check(GaugeCheckRequest(request=request, seed=seed))
        if not check.passed:
            failed = [c.transform for c in check.checks if not c.passed]
            raise TensorContractError(f"gauge invariance failed for {failed}; readings are not measurements")
        return self.reduce(request), check

    def participation_null(self, request: StageNullRequest) -> StageNullResult:
        result = self.nulls.test(request)
        if result.request_digest != request.digest():
            raise TensorContractError("null returned a result for a different request")
        self._resolvable(result)
        return result
