"""Cross node permutations with reproducible, synthetic Newton seed ensembles."""
import random
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from app.application.simulation import contracts as C
from app.infrastructure.tensors import numpy_kernels as K
from app.infrastructure.tensors.wiring import build_numpy_simulation


def seed_ensemble(extent=2.0):
    for density in (20, 30, 50, 60, 80):
        xs = np.linspace(-extent, extent, density)
        X, Y = np.meshgrid(xs, xs)
        yield np.column_stack((X.ravel(), Y.ravel()))
    xs = np.linspace(-extent, extent, 40)
    X, Y = np.meshgrid(xs, xs)
    grid = np.column_stack((X.ravel(), Y.ravel()))
    half_cell = extent / 39
    for s in range(24):
        yield grid + np.random.default_rng(1000 + s).uniform(-half_cell, half_cell, grid.shape)
    for s in range(6):
        yield np.random.default_rng(2000 + s).uniform(-extent, extent, (1600, 2))


def roots_match(reference, observed, tolerance=1e-3):
    """One-to-one same-kind geometric matching, independent of tuple order."""
    if len(reference) != len(observed):
        return False
    # Augmenting paths avoid a greedy matching failure for nearby distinct roots.
    edges = [[j for j, q in enumerate(observed)
              if r["kind"] == q["kind"] and np.hypot(r["x"] - q["x"], r["y"] - q["y"]) < tolerance]
             for r in reference]
    assigned = {}

    def assign(i, seen):
        for j in edges[i]:
            if j not in seen:
                seen.add(j)
                if j not in assigned or assign(assigned[j], seen):
                    assigned[j] = i
                    return True
        return False

    return all(assign(i, set()) for i in range(len(reference)))


class RecoveryParity(unittest.TestCase):
    def test_real_vortex_small_basin_recovers_a_cold_miss(self):
        rng = random.Random(10)
        nodes = tuple(C.InteractionNode(id=f"v{i}", x=rng.uniform(-1, 1), y=rng.uniform(-1, 1),
                                        strength=rng.uniform(-0.6, 0.6)) for i in range(7))
        req = C.NodeInteractionRequest(frame_id="synthetic-small-basin", nodes=nodes, grid=None,
                                      params=C.FieldParams(seeds=20),
                                      inflow=C.InflowSweep.grid(0, 0.3, 0.02))
        V = np.array([[n.x, n.y, n.strength] for n in req.nodes])
        self.assertEqual(K.saddle_count(V, 0.24, 0.02, 6, seeds=20), 3)
        dense = [K.saddle_count(V, inf, 0.02, 6, seeds=80) for inf in req.inflow.values]
        self.assertEqual(dense, [4] * 16)
        service, _, _ = build_numpy_simulation()
        result = service.interactions.simulate(req)
        self.assertEqual(result.saddle_curve, tuple(dense))
        self.assertEqual(result.events, ())

    def test_matching_is_one_to_one_and_kind_sensitive(self):
        a = [{"x": 0, "y": 0, "kind": "saddle"}, {"x": 0.01, "y": 0, "kind": "saddle"}]
        self.assertTrue(roots_match(a, list(reversed(a))))
        self.assertFalse(roots_match(a, [a[0], a[0]]))
        self.assertFalse(roots_match(a, [a[0], dict(a[1], kind="centre")]))

    def test_ensemble_schedule(self):
        seeds = list(seed_ensemble())
        self.assertEqual(len(seeds), 35)
        self.assertEqual([len(s) for s in seeds[:5]], [400, 900, 2500, 3600, 6400])
        np.testing.assert_array_equal(seeds[-1], np.random.default_rng(2005).uniform(-2, 2, (1600, 2)))

    def test_node_shuffle_cross_seed_ensemble(self):
        rng = random.Random(3)
        nodes = tuple(C.InteractionNode(id=f"v{i}", x=rng.uniform(-1, 1), y=rng.uniform(-1, 1),
                                        strength=rng.uniform(-0.6, 0.6)) for i in range(7))
        req = C.NodeInteractionRequest(frame_id="synthetic-recovery",
                                      nodes=nodes, grid=None,
                                      inflow=C.InflowSweep(values=(0.0, 0.05, 0.1, 0.2, 0.3)))
        shuffled = req.model_dump()
        shuffled["nodes"] = tuple(reversed(shuffled["nodes"]))
        other = C.NodeInteractionRequest.model_validate(shuffled)
        self.assertEqual(req.digest(), other.digest())
        changed = list(nodes)
        changed[0] = changed[0].model_copy(update={"strength": changed[0].strength + 0.01})
        self.assertNotEqual(req.digest(), req.model_copy(update={"nodes": tuple(changed)}).digest())
        solve = K.critical_points
        service, store, _ = build_numpy_simulation()
        baseline = service.interactions.simulate(req)
        self.assertTrue(baseline.events)
        for index, seeds in enumerate(seed_ensemble()):
            def seeded(*args, **kwargs):
                kwargs["seed_points"] = seeds
                return solve(*args, **kwargs)

            with self.subTest(ensemble=index), patch.object(K, "critical_points", side_effect=seeded):
                a, b = service.interactions.simulate(req), service.interactions.simulate(other)
                self.assertEqual(a.request_digest, b.request_digest)
                self.assertEqual(a.slices, b.slices)
                self.assertEqual(a.events, b.events)
                np.testing.assert_array_equal(store.get(a.coupling), store.get(b.coupling))
                np.testing.assert_array_equal(store.get(a.node_velocity), store.get(b.node_velocity))
                self.assertEqual(a.saddle_curve, baseline.saddle_curve)
                for ref, got in zip(baseline.slices, a.slices):
                    self.assertTrue(roots_match([p.model_dump() for p in ref.points if p.kind == C.PointKind.SADDLE],
                                                [p.model_dump() for p in got.points if p.kind == C.PointKind.SADDLE]))
                self.assertEqual(len(a.events), len(baseline.events))
                for ref, got in zip(baseline.events, a.events):
                    self.assertEqual((ref.saddles_before, ref.saddles_after),
                                     (got.saddles_before, got.saddles_after))
                    self.assertLessEqual(abs(ref.inflow - got.inflow), 1e-4)


if __name__ == "__main__":
    unittest.main()
