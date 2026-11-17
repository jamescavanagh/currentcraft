"""Gauge adapters. Arrays are read from and written to the simulation slice's InMemoryNumpyTensorStore."""

from __future__ import annotations

import numpy as np

from app.application.gauge.contracts import (EMBEDDINGS_SPEC, FlowSide, GaugeCheck, GaugeCheckRequest, GaugeCheckResult,
                                             GaugeRequest, GaugeResult, LoopWinding, StageNullRequest, StageNullResult,
                                             co_participation_labels)
from app.application.simulation.tensors import TensorRef
from app.infrastructure.tensors.numpy_store import InMemoryNumpyTensorStore

from . import participation_kernels as PK
from .lattice_kernels import reduce_arrays, wrap

_FLOW = {FlowSide.SUPPLY: 1, FlowSide.DEMAND: -1, FlowSide.NEUTRAL: 0}


def put_embeddings(store: InMemoryNumpyTensorStore, embeddings: np.ndarray, producer: str = "caller") -> TensorRef:
    """Infrastructure entry for embeddings: float64 N x K, validated against EMBEDDINGS_SPEC."""
    return store.put(EMBEDDINGS_SPEC, np.ascontiguousarray(embeddings, dtype=np.float64), producer=producer)


def _inputs(req: GaugeRequest, X: np.ndarray):
    ids = [n.id for n in req.nodes]
    rank = np.empty(len(ids), dtype=np.int64)
    rank[np.argsort(np.array(ids, dtype=object), kind="stable")] = np.arange(len(ids))
    flow = np.array([_FLOW[n.flow] for n in req.nodes], dtype=np.int64)
    pos = {i: t for t, i in enumerate(ids)}
    loops = tuple(tuple(pos[i] for i in loop.node_ids) for loop in req.loops)
    p = req.params
    kw = dict(k=p.k, planarity_min=p.planarity_min, director_ratio_min=p.director_ratio_min, reliability_min=p.reliability_min,
              director_mode=p.director_mode, supersaturation_threshold=p.supersaturation_threshold)
    return ids, rank, flow, loops, kw


class NumpyGaugeReductionAdapter:
    """Implements GaugeReductionPort."""

    PRODUCER = "NumpyGaugeReductionAdapter"

    def __init__(self, store: InMemoryNumpyTensorStore):
        self.store = store

    def reduce(self, request: GaugeRequest) -> GaugeResult:
        X = self.store.get(request.embeddings)
        ids, rank, flow, loops, kw = _inputs(request, X)
        out = reduce_arrays(X, rank, flow, loops=loops, **kw)
        n_links, n_tri = out["edge_index"].shape[1], out["triangles"].shape[1]
        b = {"N": len(ids), "F": out["node_gauges"].shape[1], "E": n_links, "T": n_tri}
        refs = {name: self.store.put(spec, out[name], producer=self.PRODUCER, bindings=b) for name, spec in GaugeResult.TENSORS.items()}
        return GaugeResult(frame_id=request.frame_id, request_digest=request.digest(), embeddings_sha256=request.embeddings.sha256,
                           director_mode=request.params.director_mode, charge_quantum=out["charge_quantum"], node_ids=tuple(ids),
                           n_valid=out["n_valid"], n_links=n_links, n_triangles=n_tri, orientation_conflicts=out["orientation_conflicts"],
                           global_link_coherence=out["global_link_coherence"], net_charge=out["net_charge"],
                           loops=tuple(LoopWinding(loop_id=l.id, **w) for l, w in zip(request.loops, out["loops"])), **refs)


def _keyed(out: dict, ids: list[str]) -> dict:
    """Index every invariant by node ids so runs on transformed inputs can be compared."""
    ei, tr = out["edge_index"], out["triangles"]
    edges = {(ids[a], ids[b]): (out["edge_link"][t], out["edge_reliability"][t], out["edge_connection"][t])
             for t, (a, b) in enumerate(ei.T)}
    tris = {(ids[a], ids[b], ids[c]): (out["triangle_holonomy"][t], out["triangle_charge"][t], int(out["triangle_z2"][t]))
            for t, (a, b, c) in enumerate(tr.T)}
    nodes = {ids[i]: (bool(out["node_mask"][i]), out["node_gauges"][i]) for i in range(len(ids))}
    return dict(edges=edges, tris=tris, nodes=nodes, loops=[w.get("winding") for w in out["loops"]])


def _nan_eq_dev(x, y, period=None):
    if np.isnan(x) and np.isnan(y):
        return 0.0
    if np.isnan(x) or np.isnan(y):
        return np.inf
    d = x - y
    if period is not None:
        d = (d + period / 2) % period - period / 2
    return abs(float(d))


def _compare(base: dict, other: dict, link_period: float) -> tuple[bool, float, float]:
    same = (base["edges"].keys() == other["edges"].keys() and base["tris"].keys() == other["tris"].keys()
            and all(base["nodes"][k][0] == other["nodes"][k][0] for k in base["nodes"]))
    dev = 0.0
    move = 0.0
    for k in base["nodes"]:
        a, b = base["nodes"][k][1], other["nodes"][k][1]
        dev = max(dev, float(np.max(np.abs(a - b) / np.maximum(1.0, np.maximum(np.abs(a), np.abs(b))))))
    for k in base["edges"].keys() & other["edges"].keys():
        (l1, r1, c1), (l2, r2, c2) = base["edges"][k], other["edges"][k]
        dev = max(dev, _nan_eq_dev(l1, l2, link_period), abs(r1 - r2))
        move = max(move, _nan_eq_dev(c1, c2, 2 * np.pi))
    for k in base["tris"].keys() & other["tris"].keys():
        (h1, q1, z1), (h2, q2, z2) = base["tris"][k], other["tris"][k]
        dev = max(dev, _nan_eq_dev(h1, h2, 2 * np.pi), _nan_eq_dev(q1, q2), float(z1 != z2))
    for w1, w2 in zip(base["loops"], other["loops"]):
        if (w1 is None) != (w2 is None):
            same = False
        elif w1 is not None:
            dev = max(dev, abs(w1 - w2))
    return same, dev, move


class NumpyGaugeInvarianceAdapter:
    """Implements GaugeInvariancePort: one run per transform, compared by node id against the base run."""

    def __init__(self, store: InMemoryNumpyTensorStore):
        self.store = store

    def check(self, request: GaugeCheckRequest) -> GaugeCheckResult:
        req = request.request
        X = np.asarray(self.store.get(req.embeddings), dtype=np.float64)
        ids, rank, flow, loops, kw = _inputs(req, X)
        n, K = X.shape
        rng = np.random.default_rng(request.seed)
        base = _keyed(reduce_arrays(X, rank, flow, loops=loops, **kw), ids)
        link_period = np.pi if req.params.director_mode == "principal_axis" else 2 * np.pi
        checks = []
        for name in request.transforms:
            if name == "permutation":
                perm = rng.permutation(n)
                pos = {old: new for new, old in enumerate(perm)}
                out = reduce_arrays(X[perm], rank[perm], flow[perm], loops=tuple(tuple(pos[i] for i in c) for c in loops), **kw)
                other = _keyed(out, [ids[i] for i in perm])
            else:
                Xt, hooks = X, {}
                if name == "frame_rotation":
                    hooks["alpha"] = rng.uniform(-np.pi, np.pi, n)
                elif name == "frame_flip":
                    hooks["flips"] = rng.random(n) < 0.5
                elif name == "global_rotation":
                    Q, _ = np.linalg.qr(rng.normal(size=(K, K)))
                    Xt = X @ Q
                elif name == "translation":
                    Xt = X + rng.normal(size=K) * 10.0 * (np.abs(X).max() + 1.0)
                elif name == "scale":
                    Xt = X * 1000.0
                other = _keyed(reduce_arrays(Xt, rank, flow, loops=loops, **kw, **hooks), ids)
            same, dev, move = _compare(base, other, link_period)
            moved_ok = name != "frame_rotation" or not base["edges"] or move > 1e-3
            checks.append(GaugeCheck(transform=name, same_structure=same, invariant_max_dev=min(dev, 1e300),
                                     gauge_dependent_max_change=move, passed=bool(same and dev <= request.tolerance and moved_ok)))
        return GaugeCheckResult(frame_id=req.frame_id, request_digest=req.digest(), checks=tuple(checks),
                                passed=all(c.passed for c in checks))


class NumpyParticipationNullAdapter:
    """Implements ParticipationNullPort."""

    PRODUCER = "NumpyParticipationNullAdapter"

    def __init__(self, store: InMemoryNumpyTensorStore):
        self.store = store

    def test(self, request: StageNullRequest) -> StageNullResult:
        rng = np.random.default_rng(request.seed)
        pairs = request.pairs
        a, b, st = [p.a for p in pairs], [p.b for p in pairs], [p.stage for p in pairs]
        loc = np.array([p.local_score for p in pairs])
        glo = np.array([p.global_score for p in pairs])
        y = np.array(co_participation_labels(request.participation, pairs), dtype=np.int64)
        used = sorted(s for s in set(st) if len(set(y[[i for i, x in enumerate(st) if x == s]])) == 2)
        groups = [np.array([i for i, x in enumerate(st) if x == s], dtype=np.int64) for s in used]
        keep = np.concatenate(groups)
        obs_l, obs_g = PK.stratified_auc(loc, y, groups), PK.stratified_auc(glo, y, groups)

        stage_sets: dict[str, dict[str, set[str]]] = {}
        for e in request.participation:
            stage_sets.setdefault(e.stage, {}).setdefault(e.resource_id, set()).add(e.process_id)
        null = np.empty((request.n_rewires, 2))
        for r in range(request.n_rewires):
            yr = PK.labels(PK.curveball(stage_sets, rng, request.trades_per_node), a, b, st)
            null[r] = PK.stratified_auc(loc, yr, groups), PK.stratified_auc(glo, yr, groups)

        boot = np.empty(request.n_bootstrap)
        for t in range(request.n_bootstrap):
            gs = [g[rng.integers(0, len(g), len(g))] for g in groups]
            idx = np.concatenate(gs)
            off = np.cumsum([0] + [len(g) for g in gs])
            gl = [np.arange(off[i], off[i + 1]) for i in range(len(gs))]
            boot[t] = PK.stratified_auc(loc[idx], y[idx], gl) - PK.stratified_auc(glo[idx], y[idx], gl)

        lo, hi = np.quantile(boot, [request.alpha / 2, 1 - request.alpha / 2])
        p_l = (1 + int((null[:, 0] >= obs_l).sum())) / (request.n_rewires + 1)
        p_g = (1 + int((null[:, 1] >= obs_g).sum())) / (request.n_rewires + 1)
        diff = obs_l - obs_g
        verdict = ("not_above_null" if p_l > request.alpha else
                   "local_beats_global" if lo > 0 and diff >= request.gain_bar else "local_signal_no_gain")
        refs = {"null_auc": self.store.put(StageNullResult.TENSORS["null_auc"], null, producer=self.PRODUCER),
                "bootstrap_diff": self.store.put(StageNullResult.TENSORS["bootstrap_diff"], boot, producer=self.PRODUCER)}
        return StageNullResult(frame_id=request.frame_id, request_digest=request.digest(), stages_used=tuple(used),
                               n_pairs=int(len(keep)), n_positive=int(y[keep].sum()), auc_local=obs_l, auc_global=obs_g,
                               auc_diff=diff, diff_ci_low=float(lo), diff_ci_high=float(hi), p_local=p_l, p_global=p_g,
                               verdict=verdict, **refs)
