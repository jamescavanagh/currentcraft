import doctest
import math
import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

import numpy as np  # noqa: E402

from app.application import probe as PR  # noqa: E402
from app.application.probe import (Aperture, Bracket, CandidateRequest, LabelBook, LabelError, LabelEvent,  # noqa: E402
                                   LensRequest, PlatePose, ProbeCloud, ProbeRequest, RecordStrength, RecordText,
                                   bracket_state, bracket_step)
from app.infrastructure.gauge.winding import measure_velocity_winding  # noqa: E402
from app.infrastructure.probe import build_numpy_probe, put_cloud  # noqa: E402
from app.infrastructure.probe import kernels as K  # noqa: E402

WHEN = datetime(2026, 11, 12, 9, tzinfo=timezone.utc)
RNG = np.random.default_rng(2)
A = np.c_[RNG.normal(-0.6, 0.08, 30), RNG.normal(0, 0.08, 30), RNG.normal(0, 0.03, 30)]
B = np.c_[RNG.normal(0.6, 0.08, 30), RNG.normal(0, 0.08, 30), RNG.normal(0, 0.03, 30)]
IDS = tuple(f"r{i:02}" for i in range(60))
SERVICE, STORE, BROKER = build_numpy_probe()
POS = put_cloud(STORE, np.vstack([A, B]))
TEXTS = tuple(RecordText(id=i, title=t) for i, t in zip(IDS, ["GateDecision"] * 30 + ["PurchaseOrder"] * 30))


def cloud(**kw):
    base = dict(cloud_id="t", ids=IDS, positions=POS, projection_ref="synthetic", texts=TEXTS)
    base.update(kw)
    return ProbeCloud(**base)


def request(cl=None, **kw):
    base = dict(cloud=cl or cloud(), pose=PlatePose(origin=(0, 0, 0), normal=(0, 0, 1), slab_half_width=0.2),
                aperture=Aperture(center=(0.0, 0.0), radius=1.0),
                offset_bracket=Bracket(lo=-0.5, hi=0.5), radius_bracket=Bracket(lo=0.2, hi=2.0))
    base.update(kw)
    return ProbeRequest(**base)


class AnalyticControls(unittest.TestCase):
    """docs/pipelines/PROBE.md control table, on a centred unit ring."""

    def ring(self, L, K_=512):
        phi = 2 * math.pi * np.arange(K_) / K_
        pts = np.c_[np.cos(phi), np.sin(phi)]
        vel, jac = K.linear_field(L, pts)
        circ, eta, leak, masks = K.ring_readings(vel, jac, phi, 1.0)
        bound = np.full(K_, np.linalg.norm(np.asarray(L, dtype=float), 2))
        w = measure_velocity_winding(vel, phi, 1.0, derivative_bound=bound, bound_provenance="linear field: ||L||_2")
        return circ, eta, leak, masks, w

    def test_rotation(self):
        circ, eta, leak, _, w = self.ring([[0, -1], [1, 0]])
        self.assertAlmostEqual(eta, 1.0); self.assertAlmostEqual(leak, 0.0, places=12)
        self.assertAlmostEqual(circ, 2 * math.pi, places=6); self.assertEqual(w.certified_index, 1)

    def test_shear(self):
        _, eta, leak, _, w = self.ring([[0, 1], [0, 0]])
        self.assertAlmostEqual(eta, 0.5)
        self.assertAlmostEqual(leak, 2 / (2 + math.pi), places=4)
        self.assertEqual(w.status, "invalid")

    def test_saddle(self):
        _, eta, leak, _, w = self.ring([[1, 0], [0, -1]])
        self.assertAlmostEqual(eta, 0.0); self.assertAlmostEqual(leak, 0.5, places=4); self.assertEqual(w.certified_index, -1)

    def test_translation(self):
        phi = 2 * math.pi * np.arange(512) / 512
        vel = np.tile([1.0, 0.0], (512, 1)); jac = np.zeros((512, 2, 2))
        _, eta, leak, masks = K.ring_readings(vel, jac, phi, 1.0)
        self.assertIsNone(eta); self.assertIn("eta_kin: gradient below floor", masks); self.assertAlmostEqual(leak, 0.5, places=4)
        w = measure_velocity_winding(vel, phi, 1.0, derivative_bound=np.zeros(512), bound_provenance="constant field")
        self.assertEqual(w.certified_index, 0)

    def test_dilation(self):
        _, eta, leak, _, w = self.ring([[1, 0], [0, 1]])
        self.assertAlmostEqual(eta, 0.0); self.assertAlmostEqual(leak, 1.0); self.assertEqual(w.certified_index, 1)


class Brackets(unittest.TestCase):
    def test_hard_pushes_never_leave(self):
        b = Bracket(lo=-1, hi=1)
        v = 0.0
        for i in range(10000):
            s = bracket_step(b, v, velocity=1e6 * (1 if i % 2000 < 1000 else -1), dt=1.0)
            v = s.value
            self.assertTrue(-1 < v < 1)
            self.assertTrue(math.isfinite(s.state.barrier))
        self.assertTrue(bracket_step(b, 0.0, velocity=1e6, dt=1.0).state.at_wall)

    def test_inward_unscaled_and_barrier_monotone(self):
        b = Bracket(lo=0, hi=2)
        self.assertAlmostEqual(bracket_step(b, 1.9, velocity=-0.5, dt=1.0).value, 1.4, places=9)
        vals = [bracket_state(b, x).barrier for x in (1.0, 1.4, 1.8, 1.95)]
        self.assertEqual(vals, sorted(vals))
        self.assertEqual(vals[0], 0.0)

    def test_outward_is_slowed_near_wall(self):
        b = Bracket(lo=-1, hi=1, margin=0.0)
        near = bracket_step(b, 0.9, velocity=0.01, dt=1.0).applied_displacement
        mid = bracket_step(b, 0.0, velocity=0.01, dt=1.0).applied_displacement
        self.assertLess(near, mid)
        self.assertAlmostEqual(near, 0.01 * (1 - 0.81), places=4)

    def test_gain_recentres(self):
        b = Bracket(lo=-1, hi=1, gain=2.0)
        self.assertLess(abs(bracket_step(b, 0.8, velocity=0.0, dt=1.0).value), 0.8)

    def test_start_outside_rejected(self):
        with self.assertRaises(ValueError):
            bracket_step(Bracket(lo=0, hi=1), 1.5, 0.1, 1.0)
        with self.assertRaisesRegex(ValueError, "outside its bracket"):
            request(pose=PlatePose(origin=(0, 0, 0), normal=(0, 0, 1), slab_half_width=0.2, offset=0.6))


class Geometry(unittest.TestCase):
    def test_phase_rotates_coordinates(self):
        X = np.array([[1.0, 0.0, 0.0], [0.0, 1.0, 0.0]])
        ne, eu, ev = K.plate_frame((0, 0, 1), 0, 0, 0.0)
        _, uv0 = K.slab(X, (0, 0, 0), ne, eu, ev, 0.0, 1.0)
        _, uv1 = K.slab(X, (0, 0, 0), *K.plate_frame((0, 0, 1), 0, 0, 0.3), 0.0, 1.0)
        R = np.array([[math.cos(-0.3), -math.sin(-0.3)], [math.sin(-0.3), math.cos(-0.3)]])
        np.testing.assert_allclose(uv1, uv0 @ R.T, atol=1e-12)

    def test_tilt_and_yaw(self):
        ne0, _, _ = K.plate_frame((0, 0, 2), 0, 45, 0)
        np.testing.assert_allclose(ne0, [0, 0, 1])
        ne, _, _ = K.plate_frame((0, 0, 1), 30, 0, 0)
        self.assertAlmostEqual(float(ne @ np.array([0, 0, 1])), math.cos(math.radians(30)))
        ne90, _, _ = K.plate_frame((0, 0, 1), 30, 90, 0)
        self.assertAlmostEqual(float(ne90 @ ne), math.cos(math.radians(30)) ** 2, places=12)  # precession keeps the cone


class Readings(unittest.TestCase):
    def test_single_vortex_at_centre(self):
        X = np.vstack([[0.0, 0.0, 0.0], RNG.normal(0, 1, (20, 3)) + [5, 5, 0]])
        ids = tuple(f"v{i}" for i in range(21))
        for g in (1.0, -1.0):
            cl = ProbeCloud(cloud_id="v", ids=ids, positions=put_cloud(STORE, X), projection_ref="synthetic",
                            strengths=(RecordStrength(id="v0", strength=g, source_ref="test"),))
            r = SERVICE.measure(request(cl, aperture=Aperture(center=(0.0, 0.0), radius=0.4)))
            # Outside its core a point vortex is irrotational: full circulation, yet almost pure strain.
            self.assertLess(r.ring.eta_kin, 0.01)
            self.assertAlmostEqual(r.ring.leakage, 0.0, places=9)
            core = SERVICE.measure(request(cl, aperture=Aperture(center=(0.0, 0.0), radius=0.4, ring_samples=128),
                                           radius_bracket=Bracket(lo=0.2, hi=2.0)))
            self.assertEqual(core.ring.certified_index, 1)
            self.assertAlmostEqual(r.ring.circulation, g * 0.16 / (0.16 + 0.09 ** 2), places=6)
            self.assertEqual((r.ring.winding_status, r.ring.certified_index), ("certified", 1))
            self.assertEqual(r.spin.balance, 1.0 if g > 0 else -1.0)
            self.assertGreater(r.spin.local_spin * g, 0)

    def test_inside_the_core_rotation_dominates(self):
        X = np.vstack([[0.0, 0.0, 0.0], RNG.normal(0, 1, (20, 3)) + [5, 5, 0]])
        ids = tuple(f"c{i}" for i in range(21))
        cl = ProbeCloud(cloud_id="c", ids=ids, positions=put_cloud(STORE, X), projection_ref="synthetic",
                        strengths=(RecordStrength(id="c0", strength=1.0, source_ref="test"),))
        r = SERVICE.measure(request(cl, aperture=Aperture(center=(0.0, 0.0), radius=0.02),
                                    radius_bracket=Bracket(lo=0.01, hi=0.05)))
        self.assertGreater(r.ring.eta_kin, 0.9)

    def test_states_plane_and_digest(self):
        r = SERVICE.measure(request())
        self.assertEqual((r.states.total, r.states.in_slab, r.states.in_aperture, r.states.with_strength), (60, 60, 60, 0))
        self.assertTrue(r.plane.valid)
        self.assertLess(r.plane.tilt_to_plate_deg, 10)
        self.assertIsNone(r.spin.balance)
        self.assertIsNone(r.ring.eta_kin)  # no vortices: masked, not zero
        self.assertEqual(r.offset_state.barrier, 0.0)
        self.assertEqual(STORE.get(r.slab_coords).shape, (60, 2))

    def test_aperture_order_and_slab(self):
        r = SERVICE.measure(request(aperture=Aperture(center=(0.6, 0.0), radius=0.3)))
        self.assertTrue(all(i >= "r30" for i in r.aperture_ids))
        thin = SERVICE.measure(request(pose=PlatePose(origin=(0, 0, 0), normal=(0, 0, 1), slab_half_width=0.01)))
        self.assertLess(thin.states.in_slab, 60)


class LensAndCandidates(unittest.TestCase):
    def test_magnification_narrows_the_lens(self):
        wide = SERVICE.lens(LensRequest(probe=request(), pointer=(0.6, 0.0), magnification=1))
        narrow = SERVICE.lens(LensRequest(probe=request(), pointer=(0.6, 0.0), magnification=8))
        self.assertLess(len(narrow.records), len(wide.records))
        self.assertAlmostEqual(narrow.lens_radius, 1.0 / 8)
        self.assertEqual({t.term for t in narrow.contrast_terms[:2]}, {"purchase", "order"})
        self.assertEqual(narrow.hovered.id, narrow.records[0].id)

    def test_words(self):
        self.assertEqual(K.words("QualityGateDefinition", "for the HTTPServer"), ["quality", "gate", "definition", "http", "server"])

    def test_two_groups_two_clusters(self):
        cs = SERVICE.candidates(CandidateRequest(probe=request()))
        self.assertEqual(len(cs.clusters), 2)
        groups = [{m < "r30" for m in c.members} for c in cs.clusters]
        self.assertEqual(sorted(map(tuple, groups)), [(False,), (True,)])  # each cluster is one group: pure
        self.assertGreaterEqual(sum(len(c.members) for c in cs.clusters), 54)  # mutual kNN may leave outliers out
        self.assertEqual(len(cs.unclustered) + sum(len(c.members) for c in cs.clusters), 60)
        self.assertTrue(all(c.status == "candidate" and c.cohesion > 0.5 for c in cs.clusters))
        again = SERVICE.candidates(CandidateRequest(probe=request()))
        self.assertEqual([c.cluster_id for c in cs.clusters], [c.cluster_id for c in again.clusters])


class Labels(unittest.TestCase):
    def test_record_publish_and_conflicts(self):
        cl = cloud()
        book = LabelBook(cl, BROKER)
        dig = request().digest()
        ev = book.record(LabelEvent(target_kind="cluster", target_ids=("r01", "r02"), label="gate", labeler_role="coordinator",
                                    blind=True, occurred_at=WHEN, reading_digest=dig))
        self.assertEqual((ev.topic, ev.kind, ev.epistemic_status), ("hil/label/cluster", "hil.label", "computed"))
        book.record(LabelEvent(target_kind="record", target_ids=("r02",), label="order", labeler_role="sme", blind=True,
                               occurred_at=WHEN, reading_digest=dig))
        self.assertEqual(book.conflicts(), {"r02": ("gate", "order")})
        with self.assertRaises(LabelError):
            book.record(LabelEvent(target_kind="record", target_ids=("nope",), label="x", labeler_role="r", blind=False,
                                   occurred_at=WHEN, reading_digest=dig))

    def test_label_shape_rules(self):
        base = dict(label="x", labeler_role="r", blind=False, occurred_at=WHEN, reading_digest="0" * 64)
        for kind, ids in (("record", ("a", "b")), ("pair", ("a",)), ("cluster", ("a",))):
            with self.assertRaises(ValueError):
                LabelEvent(target_kind=kind, target_ids=ids, **base)
        with self.assertRaisesRegex(ValueError, "timezone"):
            LabelEvent(target_kind="record", target_ids=("a",), **{**base, "occurred_at": datetime(2026, 11, 12)})


class Docs(unittest.TestCase):
    def test_fields_described_and_doctests(self):
        for m in PR.CONTRACTS:
            for name, f in m.model_fields.items():
                self.assertTrue(f.description, f"{m.__name__}.{name}")
        from app.application.probe import barrier
        self.assertEqual(doctest.testmod(barrier).failed, 0)
        self.assertEqual(doctest.testfile(str(ROOT / "docs/pipelines/PROBE.md"), module_relative=False).failed, 0)


if __name__ == "__main__":
    unittest.main()
