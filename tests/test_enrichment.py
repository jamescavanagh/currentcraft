import doctest
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

import numpy as np  # noqa: E402

from app.application import enrichment as EN  # noqa: E402
from app.application.enrichment import ChamberParams, EnrichmentRequest, SlabFrame  # noqa: E402
from app.application.plate import PlateRunRequest  # noqa: E402
from app.infrastructure.enrichment import build_numpy_enrichment, put_embedding_matrix, put_labels  # noqa: E402
from app.infrastructure.enrichment import kernels as K  # noqa: E402
from app.infrastructure.plate import build_numpy_plate  # noqa: E402

PLATE, STORE, _ = build_numpy_plate()
RUN = PLATE.run(PlateRunRequest(plate_id="enrich-test", steps=30000, record_every=8, publish=False))
SVC = build_numpy_enrichment(STORE)
RNG = np.random.default_rng(4)
X = np.vstack([np.c_[RNG.normal(-2, .3, 60), RNG.normal(0, .3, 60), RNG.uniform(-1, 1, 60)],
               np.c_[RNG.normal(2, .3, 60), RNG.normal(0, .3, 60), RNG.uniform(-1, 1, 60)]])
IDS = tuple(f"r{i:03}" for i in range(120))
EMB = put_embedding_matrix(STORE, X)
SLAB = SlabFrame(origin=(0, 0, 0), normal=(0, 0, 1))


def req(**kw):
    kw = {"enrichment_id": "t", "ids": IDS, "embeddings": EMB, "slab": SLAB, "plate_run": RUN, **kw}
    return EnrichmentRequest(**kw)


BASE = SVC.enrich(req())


def stats(res):
    return {s.arm: s for s in res.arm_stats}


class Rules(unittest.TestCase):
    def test_activation_off_never_ionizes(self):
        st = stats(BASE)
        for arm in ("real-off", "null-off"):
            self.assertEqual(st[arm].droplets, st[arm].ion_free)
            self.assertFalse([p for p in BASE.passes if p.arm == arm and p.order in ("act-first", "act-only")])

    def test_lockstep_passes(self):
        self.assertEqual(len({s.passes for s in BASE.arm_stats}), 1)
        self.assertGreater(BASE.arm_stats[0].passes, 20)
        idx = {a: [p.index for p in BASE.passes if p.arm == a] for a in EN.ARMS}
        self.assertEqual(len({tuple(v) for v in idx.values()}), 1)

    def test_no_condensation_below_threshold(self):
        res = SVC.enrich(req(params=ChamberParams(S0=0.5, eps=0.1, kappa=0.0, Sc=1.0)))
        st = stats(res)
        self.assertEqual(st["real-off"].droplets, 0)
        self.assertEqual(st["null-off"].droplets, 0)

    def test_sparse_code_consistent(self):
        code, nuc, free = (STORE.get(BASE.sparse_code), STORE.get(BASE.nucleations), STORE.get(BASE.ion_free_counts))
        np.testing.assert_array_equal(code.sum(axis=2), nuc)
        self.assertTrue(np.all(free <= nuc))
        self.assertGreater(stats(BASE)["real-on"].sparsity, 0.5)

    def test_order_classes(self):
        self.assertEqual(K.order_of(None, None, True), "quiet")
        self.assertEqual(K.order_of(None, 1.0, True), "act-only")
        self.assertEqual(K.order_of(1.0, None, False), "cond-off")
        self.assertEqual(K.order_of(1.0, None, True), "cond-noact")
        self.assertEqual(K.order_of(1.0, 2.0, True), "cond-first")
        self.assertEqual(K.order_of(2.0, 1.0, True), "act-first")


class Nulls(unittest.TestCase):
    def test_axis_shuffle_preserves_marginals(self):
        Y = K.shuffle_axes(X, 7101)
        np.testing.assert_array_equal(np.sort(Y, axis=0), np.sort(X, axis=0))
        self.assertFalse(np.array_equal(Y, X))

    def test_height_preserving_keeps_every_height(self):
        n = np.array([0.3, -0.2, 0.9]); n = n / np.linalg.norm(n)
        o = np.array([0.1, 0.0, -0.2])
        Y = K.height_preserving_shuffle(X, o, n, 7101)
        np.testing.assert_allclose((Y - o) @ n, (X - o) @ n, atol=1e-12)
        self.assertFalse(np.allclose(Y, X))

    def test_excess_is_reported_against_the_chosen_null(self):
        for mode in ("axis_shuffle", "height_preserving"):
            res = SVC.enrich(req(null_mode=mode))
            st = stats(res)
            self.assertEqual(res.null_mode, mode)
            self.assertEqual(res.shortcut_excess_on, st["real-on"].shortcut_count - st["null-on"].shortcut_count)


class Shortcuts(unittest.TestCase):
    def test_planted_groups_yield_far_shortcuts(self):
        real = [c for c in BASE.shortcuts if c.arm == "real-on"]
        self.assertTrue(real)
        self.assertTrue(all(c.hops >= 4 and c.status == "candidate" for c in real))
        groups = {c.a < "r060" for c in real} | {c.b < "r060" for c in real}
        self.assertEqual(groups, {True, False})  # links the two groups

    def test_efficiency_rises_even_when_path_length_does_not(self):
        sw = stats(BASE)["real-on"].small_world
        self.assertGreater(sw.efficiency_with_shortcuts, sw.efficiency)
        self.assertGreater(sw.unreachable_fraction, sw.unreachable_fraction_with_shortcuts)

    def test_labels_enable_cross_cluster_rule_in_both_arms(self):
        lab = put_labels(STORE, [0] * 60 + [1] * 60)
        res = SVC.enrich(req(labels_real=lab, labels_null=lab))
        self.assertTrue(any(c.cross_cluster for c in res.shortcuts if c.arm == "real-on"))
        with self.assertRaisesRegex(ValueError, "both arms"):
            req(labels_real=lab)

    def test_reported_top_k_and_exact_totals(self):
        res = SVC.enrich(req(criteria=EN.ShortcutCriteria(max_reported=5)))
        for s in res.arm_stats:
            self.assertLessEqual(sum(c.arm == s.arm for c in res.shortcuts), 5)
        self.assertEqual(stats(res)["real-on"].shortcut_count, stats(BASE)["real-on"].shortcut_count)


class Provenance(unittest.TestCase):
    def test_deterministic(self):
        again = SVC.enrich(req())
        self.assertEqual(again.request_digest, BASE.request_digest)
        self.assertEqual(again.sparse_code.sha256, BASE.sparse_code.sha256)
        self.assertEqual(again.shortcuts, BASE.shortcuts)

    def test_request_rules(self):
        with self.assertRaisesRegex(ValueError, "dimension"):
            req(slab=SlabFrame(origin=(0, 0), normal=(0, 1)))
        with self.assertRaises(ValueError):
            SlabFrame(origin=(0, 0, 0), normal=(0, 0, 0))
        with self.assertRaisesRegex(ValueError, "ids"):
            EnrichmentRequest(enrichment_id="t", ids=IDS[:-1], embeddings=EMB, slab=SLAB, plate_run=RUN)

    def test_every_field_described_and_doc(self):
        for m in EN.CONTRACTS:
            for name, f in m.model_fields.items():
                self.assertTrue(f.description, f"{m.__name__}.{name}")
        self.assertEqual(doctest.testfile(str(ROOT / "docs/pipelines/EMBEDDING_ENRICHMENT.md"), module_relative=False).failed, 0)


if __name__ == "__main__":
    unittest.main()
