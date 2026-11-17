"""Simulation use cases. Orchestrate ports, enforce cross-stage rules. No numpy, no adapters imported."""

from __future__ import annotations

from .contracts import (BufferRingRequest, CnnSampleRequest, FramePipelineRequest, FramePipelineResult,
                        GraphSampleRequest, InteractionNode, NodeInteractionRequest, TensorContract)
from .ports import (BufferRingPort, CnnSamplePort, GraphTensorPort, NodeInteractionPort, TensorStorePort)
from .tensors import TensorContractError


def reflect_nodes(nodes: tuple[InteractionNode, ...], axis: str = "x") -> tuple[InteractionNode, ...]:
    """Mirror the node set across an axis. A reflection reverses circulation, so strengths are negated too.

    >>> n = InteractionNode(id="a", x=0.5, y=0.2, strength=0.3)
    >>> m = reflect_nodes((n,), axis="x")[0]
    >>> (m.x, m.y, m.strength)
    (-0.5, 0.2, -0.3)
    """
    if axis not in ("x", "y"):
        raise ValueError("axis must be 'x' or 'y'")
    return tuple(n.model_copy(update={"x": -n.x if axis == "x" else n.x, "y": -n.y if axis == "y" else n.y,
                                      "strength": -n.strength}) for n in nodes)


class SimulationService:
    def __init__(self, store: TensorStorePort, interactions: NodeInteractionPort, rings: BufferRingPort,
                 cnn: CnnSamplePort, graphs: GraphTensorPort):
        self.store, self.interactions, self.rings, self.cnn, self.graphs = store, interactions, rings, cnn, graphs

    def _resolvable(self, contract: TensorContract) -> None:
        for name, ref in contract.tensor_refs().items():
            if ref is not None and not self.store.contains(ref):
                raise TensorContractError(f"{type(contract).__name__}.{name}: ref {ref.key} not in the tensor store")

    def run_frame(self, req: FramePipelineRequest) -> FramePipelineResult:
        inter = self.interactions.simulate(NodeInteractionRequest(
            frame_id=req.frame_id, nodes=req.nodes, inflow=req.inflow, grid=req.grid, params=req.params))
        rings = self.rings.simulate(BufferRingRequest(
            frame_id=req.frame_id, nodes=req.nodes, inflow=req.ring_inflow, grid=req.grid, params=req.params,
            steps=req.ring_steps))
        cnn = self.cnn.build(CnnSampleRequest(source=inter))
        graph = self.graphs.build(GraphSampleRequest(
            frame_id=req.frame_id, nodes=req.nodes, inflow=req.ring_inflow, params=req.params,
            edge_rule=req.edge_rule, k=req.k, rings=rings))
        for c in (inter, rings, cnn, graph):
            self._resolvable(c)
        return FramePipelineResult(frame_id=req.frame_id, interactions=inter, rings=rings, cnn=cnn, graph=graph)

    def run_reflected(self, req: FramePipelineRequest, axis: str = "x") -> FramePipelineResult:
        """The sanctioned augmentation path: reflect positions AND negate strengths, then rerun."""
        return self.run_frame(req.model_copy(update={"nodes": reflect_nodes(req.nodes, axis),
                                                     "frame_id": f"{req.frame_id}.reflect_{axis}"}))
