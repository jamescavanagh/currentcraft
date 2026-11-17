"""Numpy implementations of the simulation ports. Arrays enter and leave only through the store."""

from __future__ import annotations

import math

import numpy as np

from app.application.simulation.contracts import (CORE_KINDS, EDGE_FEATURES, NODE_FEATURES, BufferRing, BufferRingRequest,
                                                  BufferRingResult, CnnSample, CnnSampleRequest, CollisionEvent,
                                                  CriticalPoint, GraphSample, GraphSampleRequest, InflowSlice,
                                                  InteractionNode, NodeInteractionRequest, NodeInteractionResult,
                                                  NodeRole, PointKind, TransformSpec)
from app.application.simulation.tensors import TensorContractError, TensorRef

from . import numpy_kernels as K
from .numpy_store import InMemoryNumpyTensorStore

ROLES = (NodeRole.RESOURCE, NodeRole.PROCESS, NodeRole.OPERAND, NodeRole.UNASSIGNED)


def nodes_to_array(nodes: tuple[InteractionNode, ...]) -> np.ndarray:
    """Anti-corruption mapping: contract nodes -> (N, 3) float64 kernel input."""
    return np.array([[n.x, n.y, n.strength] for n in nodes], dtype=np.float64)


def _nearest(nodes, x, y):
    d = [(math.hypot(n.x - x, n.y - y), n.id) for n in nodes]
    return min(d)[1]


def _points(nodes, raw) -> tuple[CriticalPoint, ...]:
    return tuple(CriticalPoint(x=q["x"], y=q["y"], kind=PointKind(q["kind"]), det=q["det"], trace=q["trace"],
                               mu_min_abs=q["mu_min_abs"], nearest_node_id=_nearest(nodes, q["x"], q["y"]))
                 for q in raw)


class NumpyNodeInteractionAdapter:
    """Implements NodeInteractionPort."""

    name = "numpy.NodeInteraction/v1"

    def __init__(self, store: InMemoryNumpyTensorStore):
        self.store = store

    def simulate(self, req: NodeInteractionRequest) -> NodeInteractionResult:
        V, p, specs = nodes_to_array(req.nodes), req.params, NodeInteractionResult.TENSORS
        extent = req.grid.extent if req.grid else 2.0
        slices, vel, fields = [], [], []
        for inf in req.inflow.values:
            pts = _points(req.nodes, K.critical_points(V, inf, p.softening, p.scale, p.seeds, extent))
            slices.append(InflowSlice(inflow=inf, saddle_count=sum(q.kind == PointKind.SADDLE for q in pts),
                                      core_count=sum(q.kind in CORE_KINDS for q in pts), points=pts))
            u, v, *_ = K.field(V, V[:, 0], V[:, 1], inf, p.softening, p.scale)
            vel.append(np.stack([u, v], -1))
            if req.grid:
                fields.append(K.channels(V, inf, req.grid.size, req.grid.extent, p.softening, p.scale))
        counts = [s.saddle_count for s in slices]
        ev = K.collisions(V, list(req.inflow.values), counts, p.softening, p.scale, p.seeds, extent, req.refine_events)
        return NodeInteractionResult(
            frame_id=req.frame_id, request_digest=req.digest(), n_nodes=len(req.nodes), grid=req.grid,
            slices=tuple(slices), events=tuple(CollisionEvent(inflow=e[0], saddles_before=e[1], saddles_after=e[2]) for e in ev),
            coupling=self.store.put(specs["coupling"], K.coupling(V, p.softening, p.scale).astype(np.float32), self.name),
            node_velocity=self.store.put(specs["node_velocity"], np.stack(vel).astype(np.float32), self.name),
            field=self.store.put(specs["field"], np.stack(fields).astype(np.float32), self.name) if req.grid else None,
        )


class NumpyBufferRingAdapter:
    """Implements BufferRingPort: tracer advection, ring radii, occupancy ring buffer, basins."""

    name = "numpy.BufferRing/v1"

    def __init__(self, store: InMemoryNumpyTensorStore):
        self.store = store

    def simulate(self, req: BufferRingRequest) -> BufferRingResult:
        V, p, g, specs = nodes_to_array(req.nodes), req.params, req.grid, BufferRingResult.TENSORS
        raw = K.critical_points(V, req.inflow, p.softening, p.scale, p.seeds, g.extent)
        cores = [q for q in raw if q["kind"] in ("spiral_sink", "node_sink", "centre")]
        C = np.array([[c["x"], c["y"]] for c in cores]).reshape(-1, 2)
        X, Y = K.grid_xy(g.size, g.extent)
        P, R, T = g.size * g.size, len(cores), req.history_len
        hist = np.zeros((max(R, 1), T), np.int32)
        state = {"filled": 0, "ptr": 0}

        def label(x, y):
            if not R:
                return np.full(x.shape, -1), np.full(x.shape, np.inf)
            d = np.hypot(x[:, None] - C[:, 0], y[:, None] - C[:, 1])
            lab, dm = d.argmin(1), d.min(1)
            return np.where(dm <= req.capture_radius, lab, -1), dm

        def record(x, y, _step):
            lab, _ = label(x, y)
            hist[:, state["ptr"]] = np.bincount(lab[lab >= 0], minlength=R)[:R] if R else 0
            state["ptr"] = (state["ptr"] + 1) % T
            state["filled"] = min(T, state["filled"] + 1)

        x, y = K.advect(V, X.ravel(), Y.ravel(), req.inflow, p.softening, p.scale, req.steps, req.step_length,
                        req.record_every, record if R else None)
        lab, dm = label(x, y)
        if state["filled"] == T:  # unroll the circular buffer so the oldest record comes first
            hist = np.roll(hist, -state["ptr"], axis=1)
        else:
            hist = np.concatenate([np.zeros((hist.shape[0], T - state["filled"]), np.int32), hist[:, :state["filled"]]], 1)
        rings = []
        for i, c in enumerate(cores):
            m = lab == i
            rings.append(BufferRing(index=i, core_x=c["x"], core_y=c["y"], spiral=c["kind"] == "spiral_sink",
                                    radius=float(np.median(dm[m])) if m.any() else None, occupancy=int(m.sum()),
                                    share=float(m.sum()) / P, nearest_node_id=_nearest(req.nodes, c["x"], c["y"])))
        unassigned = float((lab < 0).sum()) / P
        return BufferRingResult(
            frame_id=req.frame_id, request_digest=req.digest(), inflow=req.inflow, grid=g, tracers=P, history_len=T,
            history_filled=state["filled"] if R else 0, rings=tuple(rings), unassigned_share=unassigned,
            basins=self.store.put(specs["basins"], lab.reshape(g.size, g.size).astype(np.int8), self.name),
            occupancy_history=self.store.put(specs["occupancy_history"], hist, self.name) if R else None,
            tracers_final=self.store.put(specs["tracers_final"], np.stack([x, y], -1).astype(np.float32), self.name),
        )


class NumpyCnnSampleAdapter:
    """Implements CnnSamplePort: field -> x, oracle critical points -> heatmaps and count targets."""

    name = "numpy.CnnSample/v1"

    def __init__(self, store: InMemoryNumpyTensorStore):
        self.store = store

    def build(self, req: CnnSampleRequest) -> CnnSample:
        src, specs = req.source, CnnSample.TENSORS
        if src.field is None or src.grid is None:
            raise TensorContractError("CNN sample needs a NodeInteractionResult with a field tensor")
        x = self.store.get(src.field).astype(np.float32)
        if req.normalize == "per_channel_std":
            sd = x.std(axis=(0, 2, 3), keepdims=True)
            x = x / np.where(sd > 0, sd, 1)
        G, E = src.grid.size, src.grid.extent
        X, Y = K.grid_xy(G, E)
        px = (G - 1) / (2 * E)
        heat = np.zeros((len(src.slices), 2, G, G), np.float32)
        for s, sl in enumerate(src.slices):
            for q in sl.points:
                ch = 0 if q.kind == PointKind.SADDLE else 1 if q.kind in CORE_KINDS else None
                if ch is None:
                    continue
                gk = np.exp(-(((X - q.x) * px) ** 2 + ((Y - q.y) * px) ** 2) / (2 * req.heat_sigma_px ** 2))
                heat[s, ch] = np.maximum(heat[s, ch], gk)
        return CnnSample(
            frame_id=src.frame_id, source_digest=src.request_digest, inflows=tuple(s.inflow for s in src.slices),
            normalization=req.normalize,
            x=self.store.put(specs["x"], np.ascontiguousarray(x, np.float32), self.name),
            heat=self.store.put(specs["heat"], heat, self.name),
            saddle_count=self.store.put(specs["saddle_count"], np.array([s.saddle_count for s in src.slices], np.int16), self.name),
            core_count=self.store.put(specs["core_count"], np.array([s.core_count for s in src.slices], np.int16), self.name),
        )


class NumpyGraphTensorAdapter:
    """Implements GraphTensorPort: PyG-style x [N,F], edge_index [2,E] int64, edge_attr [E,D]."""

    name = "numpy.GraphTensor/v1"

    def __init__(self, store: InMemoryNumpyTensorStore):
        self.store = store

    def build(self, req: GraphSampleRequest) -> GraphSample:
        V, p, specs = nodes_to_array(req.nodes), req.params, GraphSample.TENSORS
        N = len(V)
        u, v, ux, _uy, _vx, vy = K.field(V, V[:, 0], V[:, 1], req.inflow, p.softening, p.scale)
        extent = req.rings.grid.extent if req.rings else 2.0
        sad = [q for q in K.critical_points(V, req.inflow, p.softening, p.scale, p.seeds, extent) if q["kind"] == "saddle"]
        if sad:
            S = np.array([[q["x"], q["y"]] for q in sad])
            near_sad = np.hypot(V[:, None, 0] - S[:, 0], V[:, None, 1] - S[:, 1]).min(1)
        else:
            near_sad = np.full(N, -1.0)  # documented sentinel: no saddle at this inflow
        basin_share = np.zeros(N)
        if req.rings is not None:
            if not math.isclose(req.rings.inflow, req.inflow):
                raise TensorContractError("rings were simulated at a different inflow")
            if not req.rings.basins:
                raise TensorContractError("rings has no basins tensor")
            basins = self.store.get(req.rings.basins)
            g = req.rings.grid
            col = np.clip(np.rint((V[:, 0] + g.extent) / (2 * g.extent) * (g.size - 1)), 0, g.size - 1).astype(int)
            row = np.clip(np.rint((g.extent - V[:, 1]) / (2 * g.extent) * (g.size - 1)), 0, g.size - 1).astype(int)
            shares = {r.index: r.share for r in req.rings.rings}
            basin_share = np.array([shares.get(int(b), 0.0) for b in basins[row, col]])
        role = np.array([[n.role == r for r in ROLES] for n in req.nodes], np.float64)
        feats = np.column_stack([V[:, 0], V[:, 1], V[:, 2], np.abs(V[:, 2]), np.sign(V[:, 2]), role,
                                 np.hypot(u, v), ux + vy, near_sad, basin_share])
        assert feats.shape[1] == len(NODE_FEATURES)
        k = K.coupling(V, p.softening, p.scale)
        dist = np.hypot(V[:, None, 0] - V[None, :, 0], V[:, None, 1] - V[None, :, 1])
        if req.edge_rule == "knn":
            kk = min(req.k, N - 1)
            order = np.argsort(dist + np.eye(N) * 1e9, axis=1)[:, :kk]
            src = np.repeat(np.arange(N), kk)
            dst = order.ravel()
        else:
            src, dst = np.nonzero((np.abs(k) >= req.coupling_threshold) & ~np.eye(N, dtype=bool))
        # message direction: j influences i  ->  edge j -> i, coupling k_ij
        edge_index = np.stack([dst, src]).astype(np.int64)
        kij = k[src, dst]
        same = (np.sign(V[src, 2]) == np.sign(V[dst, 2])).astype(np.float64)
        attr = np.column_stack([kij, np.abs(kij), dist[src, dst], same]).reshape(-1, len(EDGE_FEATURES))
        return GraphSample(
            frame_id=req.frame_id, inflow=req.inflow, edge_rule=req.edge_rule, node_ids=tuple(n.id for n in req.nodes),
            x=self.store.put(specs["x"], feats.astype(np.float32), self.name),
            edge_index=self.store.put(specs["edge_index"], edge_index, self.name),
            edge_attr=self.store.put(specs["edge_attr"], attr.astype(np.float32), self.name),
        )


class NumpyTensorTransformAdapter:
    """Implements TensorTransformPort."""

    name = "numpy.Transform/v1"

    def __init__(self, store: InMemoryNumpyTensorStore):
        self.store = store

    def apply(self, spec: TransformSpec, source: TensorRef) -> TensorRef:
        a = self.store.get(source)
        if spec.op == "select_slices":
            if a.ndim == 0 or max(spec.indices) >= a.shape[0]:
                raise TensorContractError("slice index out of range")
            out, tspec = a[list(spec.indices)], source.spec
        elif spec.op == "normalize_per_channel":
            if a.ndim != 4:
                raise TensorContractError("normalize_per_channel expects a 4D SCHW tensor")
            sd = a.std(axis=(0, 2, 3), keepdims=True)
            out, tspec = (a / np.where(sd > 0, sd, 1)).astype(a.dtype), source.spec
        else:  # astype
            if source.spec.dtype not in ("float32", "float64"):
                raise TensorContractError("astype only converts between float dtypes")
            out = a.astype(spec.dtype)
            tspec = source.spec.model_copy(update={"dtype": spec.dtype, "name": f"{source.spec.name}.{spec.dtype}"})
        return self.store.put(tspec, np.ascontiguousarray(out), self.name)
