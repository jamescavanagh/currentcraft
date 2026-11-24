"""Synthetic numerical controls; no source-derived fixtures."""
import math
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from app.infrastructure.tensors import numpy_kernels as K


def narrow_field(V, x, y, inflow, softening, scale):
    """A translating saddle with a narrow Newton basin, not a vortex field."""
    centre = 2 / 39 + inflow * 0.004
    z = (x - centre) / 0.001
    t = np.tanh(z)
    zero = np.zeros_like(x)
    return t, -y, (1 - t * t) / 0.001, zero, zero, -np.ones_like(y)


def fold_field(V, x, y, inflow, softening, scale):
    zero = np.zeros_like(x)
    return x * x + inflow - 0.1, -y, 2 * x, zero, zero, -np.ones_like(y)


class SaddleRecovery(unittest.TestCase):
    def test_no_warm_starts_preserves_cold_result(self):
        V = np.array([[-0.5, 0, 1], [0.5, 0, 1]])
        args = (V, 0.1, 0.02, 6)
        self.assertEqual(K.critical_points(*args),
                         K.critical_points(*args, warm_starts=[]))
        self.assertEqual(K.critical_points(*args),
                         K.critical_points(*args, warm_starts=np.empty((0, 2))))

    def test_small_basin_cold_misses_continuation_recovers(self):
        # The cold kernel's Newton loop is unchanged from the pre-change
        # implementation. Its every-slice restart loses this translating root.
        with patch.object(K, "field", narrow_field):
            warm = None
            cold_counts, warm_counts = [], []
            for inf in np.linspace(0, 1, 41):
                cold = K.critical_points(None, inf, 0.02, 6)
                recovered = K.critical_points(None, inf, 0.02, 6, warm_starts=warm)
                cold_counts.append(len(cold))
                warm_counts.append(len(recovered))
                warm = recovered
            self.assertEqual(cold_counts[0], 1)
            self.assertEqual(cold_counts[-1], 0)
            self.assertEqual(warm_counts, [1] * 41)
            self.assertEqual(warm[0]["kind"], "saddle")
            self.assertAlmostEqual(warm[0]["x"], 2 / 39 + 0.004, places=8)

    def test_initial_miss_is_not_manufactured_into_a_root(self):
        with patch.object(K, "field", narrow_field):
            self.assertEqual(K.critical_points(None, 1, 0.02, 6), [])

    def test_warm_starts_are_revalidated_and_real_fold_is_not_preserved(self):
        with patch.object(K, "field", fold_field):
            before = K.critical_points(None, 0, 0.02, 6)
            self.assertTrue(any(q["kind"] == "saddle" for q in before))
            after = K.critical_points(None, 0.2, 0.02, 6, warm_starts=before)
            self.assertEqual(after, [])

    def test_warm_duplicates_are_deduplicated(self):
        with patch.object(K, "field", narrow_field):
            p = {"x": 2 / 39, "y": 0}
            pts = K.critical_points(None, 0, 0.02, 6, warm_starts=[p, p])
            self.assertEqual(len(pts), 1)

    def test_seed_validation_is_source_free(self):
        for bad in ([[math.nan, 0]], [[0, math.inf]], [1, 2], [{"x": "private", "y": 0}]):
            with self.subTest(shape=type(bad).__name__):
                with self.assertRaisesRegex(ValueError, "^Newton seeds must be finite coordinate pairs$"):
                    K.critical_points(None, 0, 0.02, 6, warm_starts=bad)
        with self.assertRaisesRegex(ValueError, "^Newton seed set must not be empty$"):
            K.critical_points(None, 0, 0.02, 6, seed_points=[])

    def test_explicit_seed_input_is_not_mutated(self):
        seeds = np.array([[2 / 39, 0.2]])
        original = seeds.copy()
        with patch.object(K, "field", narrow_field):
            self.assertEqual(len(K.critical_points(None, 0, 0.02, 6, seed_points=seeds)), 1)
        np.testing.assert_array_equal(seeds, original)

    def test_bisection_uses_both_endpoints_and_refreshes_them(self):
        left = [{"x": -1.0, "y": 0.0, "kind": "saddle"}]
        right = [{"x": 1.0, "y": 0.0, "kind": "centre"}]
        calls = []

        def solve(V, inflow, *args, warm_starts=None, **kwargs):
            calls.append((inflow, np.array(warm_starts)))
            return [{"x": inflow, "y": 0.0, "kind": "saddle" if inflow < 0.6 else "centre"}]

        with patch.object(K, "critical_points", side_effect=solve):
            events = K.collisions(None, [0.0, 1.0], [1, 0], 0.02, 6,
                                  refine=3, slice_points=[left, right])
        np.testing.assert_array_equal(calls[0][1], [[-1, 0], [1, 0]])
        np.testing.assert_array_equal(calls[1][1], [[0.5, 0], [1, 0]])
        np.testing.assert_array_equal(calls[2][1], [[0.5, 0], [0.75, 0]])
        self.assertLess(abs(events[0][0] - 0.6), 0.125)

    def test_refinement_fails_closed_on_unresolved_midpoint(self):
        left = [{"x": 0, "y": 0, "kind": "saddle"}] * 2
        right = left[:1]
        with patch.object(K, "critical_points", return_value=[]):
            with self.assertRaisesRegex(ValueError, "^Unresolved event midpoint recovery$"):
                K.collisions(None, [0, 1], [2, 1], 0.02, 6, slice_points=[left, right])

    def test_refinement_rejects_inconsistent_endpoint(self):
        with self.assertRaisesRegex(ValueError, "^Unresolved event endpoint recovery$"):
            K.collisions(None, [0, 1], [1, 0], 0.02, 6, slice_points=[[], []])

    def test_genuine_fold_event_remains_numerical(self):
        with patch.object(K, "field", fold_field):
            left = K.critical_points(None, 0, 0.02, 6)
            right = K.critical_points(None, 0.2, 0.02, 6, warm_starts=left)
            events = K.collisions(None, [0, 0.2], [1, 0], 0.02, 6,
                                  refine=12, slice_points=[left, right])
        self.assertEqual(len(events), 1)
        self.assertLess(abs(events[0][0] - 0.1), 1e-4)

    def test_bad_bracket_inputs_rejected(self):
        for inflows, counts, points in (([0, 1], [0], None), ([1, 0], [0, 1], None),
                                         ([0, 1], [0, 1], [[]])):
            with self.assertRaises(ValueError):
                K.collisions(None, inflows, counts, 0.02, 6, slice_points=points)


if __name__ == "__main__":
    unittest.main()
