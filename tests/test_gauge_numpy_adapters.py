import doctest
import os
import sys
import unittest
from collections import deque
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

import numpy as np  # noqa: E402

from app.application.gauge import (EmbeddingSpaceRef, FlowSide, GaugeCheckRequest, GaugeLoop, GaugeNode, GaugeParams,  # noqa: E402
                                   GaugeRequest, GaugeResult, gauge_nodes_from_interactions)
from app.application.simulation import InteractionNode, TensorContractError  # noqa: E402
from app.infrastructure.gauge import build_numpy_gauge, put_embeddings  # noqa: E402
from app.infrastructure.gauge.lattice_kernels import wrap  # noqa: E402
from app.infrastructure.tensors import build_numpy_simulation  # noqa: E402


def sheet(P, K=8, curve=0.3, noise=0.003, seed=0):
    rng = np.random.default_rng(seed)
    Q, _ = np.linalg.qr(rng.normal(size=(K, K)))
    Z = np.zeros((len(P), K))
    Z[:, :2] = P
    Z[:, 2] = curve * (P[:, 0] ** 2 - 0.5 * P[:, 1] ** 2)
    Z[:, 3:] = rng.normal(scale=noise, size=(len(P), K - 3))
    return Z @ Q


def streaks(seed=0):
    rng = np.random.default_rng(seed)
    x = np.arange(-1, 1, 0.025)
    return np.vstack([np.c_[x + rng.normal(0, 0.002, len(x)), np.full(len(x), y)] for y in np.linspace(-1, 1, 14)])


def annulus(n=1400, seed=0):
    rng = np.random.default_rng(seed)
    r = np.sqrt(rng.uniform(0.45 ** 2, 1.05 ** 2, n))
    t = rng.uniform(0, 2 * np.pi, n)
    return np.c_[r * np.cos(t), r * np.sin(t)]


def ring_loop(P, edge_index, r0=0.75, nsec=16):
    adj = {}
    for a, b in edge_index.T:
        adj.setdefault(int(a), set()).add(int(b))
        adj.setdefault(int(b), set()).add(int(a))
    rad, ang = np.hypot(*P.T), np.arctan2(P[:, 1], P[:, 0])
    sec = []
    for a0 in np.linspace(-np.pi, np.pi, nsec, endpoint=False):
        c = [i for i in adj if abs((ang[i] - a0 + np.pi) % (2 * np.pi) - np.pi) < np.pi / nsec]
        sec.append(min(c, key=lambda i: abs(rad[i] - r0)))
    cyc = []
    for s, t in zip(sec, sec[1:] + sec[:1]):
        prev, dq = {s: None}, deque([s])
        while dq:
            u = dq.popleft()
            for v in sorted(adj[u]):
                if v not in prev:
                    prev[v] = u
                    dq.append(v)
        path = [t]
        while path[-1] != s:
            path.append(prev[path[-1]])
        cyc += path[::-1][:-1]
    return cyc


class Reduction(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        _, cls.store, _ = build_numpy_simulation()
        cls.svc, _ = build_numpy_gauge(cls.store)
        P = streaks()
        cls.n = len(P)
        cls.req = GaugeRequest(frame_id="test-streaks", space=EmbeddingSpaceRef(model="synthetic"),
                               nodes=tuple(GaugeNode(id=f"n{i:04d}") for i in range(len(P))),
                               embeddings=put_embeddings(cls.store, sheet(P)))
        cls.res = cls.svc.reduce(cls.req)

    def test_shared_store_and_refs(self):
        self.assertIsInstance(self.res, GaugeResult)
        for name, ref in self.res.tensor_refs().items():
            self.assertTrue(self.store.contains(ref), name)
        self.assertEqual(self.store.get(self.res.node_gauges).shape, (self.n, len(self.res.node_feature_names)))
        self.assertEqual(self.res.request_digest, self.req.digest())
        self.assertGreater(self.res.n_links, 0)
        self.assertGreater(self.res.n_triangles, 0)

    def test_invariance_battery_passes_and_gauge_moves(self):
        chk = self.svc.check(GaugeCheckRequest(request=self.req, seed=3))
        self.assertTrue(chk.passed, [(c.transform, c.same_structure, c.invariant_max_dev) for c in chk.checks])
        rot = next(c for c in chk.checks if c.transform == "frame_rotation")
        self.assertGreater(rot.gauge_dependent_max_change, 0.5)   # the connection really changed
        self.assertLess(rot.invariant_max_dev, 1e-10)             # the measurements did not

    def test_charges_are_quantized(self):
        q = self.store.get(self.res.triangle_charge)
        q = q[np.isfinite(q)]
        np.testing.assert_allclose(q * 2, np.round(q * 2), atol=1e-12)

    def test_edges_are_canonical(self):
        ei = self.store.get(self.res.edge_index)
        ids = self.res.node_ids
        self.assertTrue(all(ids[a] < ids[b] for a, b in ei.T))

    def test_unknown_embeddings_ref_is_refused(self):
        _, other = build_numpy_gauge()
        svc, _ = build_numpy_gauge(other)
        with self.assertRaises(TensorContractError):
            svc.reduce(self.req)

    def test_bridge_from_interaction_nodes(self):
        g = gauge_nodes_from_interactions((InteractionNode(id="v2", x=0, y=0, strength=0.33),), {"v2": FlowSide.SUPPLY})
        self.assertEqual((g[0].id, g[0].flow), ("v2", FlowSide.SUPPLY))


class SupplyDemandWinding(unittest.TestCase):
    """PROPOSED director: supply outside r = 0.75, demand inside, so the director points outward (+-1 winding)."""

    def test_boundary_loop_winds_once(self):
        _, store, _ = build_numpy_simulation()
        svc, _ = build_numpy_gauge(store)
        P = annulus()
        side = np.hypot(*P.T) > 0.75
        ids = [f"n{i:04d}" for i in range(len(P))]
        nodes = tuple(GaugeNode(id=ids[i], flow=FlowSide.SUPPLY if side[i] else FlowSide.DEMAND) for i in range(len(P)))
        base = dict(frame_id="test-sd", space=EmbeddingSpaceRef(model="synthetic"), nodes=nodes,
                    embeddings=put_embeddings(store, sheet(P, curve=0.0)), params=GaugeParams(director_mode="supply_demand"))
        r = svc.reduce(GaugeRequest(**base))
        cyc = ring_loop(P, store.get(r.edge_index))
        ang = np.arctan2(P[cyc, 1], P[cyc, 0])
        self.assertAlmostEqual(abs(float(np.sum(wrap(np.diff(np.r_[ang, ang[0]])))) / (2 * np.pi)), 1.0, places=6)
        loop = tuple(ids[i] for i in cyc)
        back = loop[: len(loop) // 2]
        r2 = svc.reduce(GaugeRequest(**base, loops=(GaugeLoop(id="ring", node_ids=loop),
                                                    GaugeLoop(id="there-and-back", node_ids=back + back[-2:0:-1]))))
        ring, flat = r2.loops
        self.assertTrue(ring.complete and flat.complete)
        self.assertEqual(abs(ring.quantized), 1.0)
        self.assertEqual(flat.quantized, 0.0)
        chk = svc.check(GaugeCheckRequest(request=GaugeRequest(**base, loops=(GaugeLoop(id="ring", node_ids=loop),)), seed=5))
        self.assertTrue(chk.passed, [(c.transform, c.invariant_max_dev) for c in chk.checks])


class PipelineDoc(unittest.TestCase):
    def test_gauge_pipeline_doc_examples_run(self):
        cwd = os.getcwd()
        os.chdir(ROOT)
        try:
            r = doctest.testfile(str(ROOT / "docs" / "pipelines" / "GAUGE_PIPELINE.md"), module_relative=False)
        finally:
            os.chdir(cwd)
        self.assertEqual(r.failed, 0)


if __name__ == "__main__":
    unittest.main()
