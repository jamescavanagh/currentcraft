import doctest
import math
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

import numpy as np  # noqa: E402

from app.application import plate as PL  # noqa: E402
from app.application.plate import (IsoscelesParams, ObjectMassEvent, PlateFieldRequest, PlateRunRequest,  # noqa: E402
                                   PlateVortex, RingWindingRequest)
from app.infrastructure.plate import build_numpy_plate, put_points  # noqa: E402
from app.infrastructure.plate import kernels as K  # noqa: E402

BASE = dict(side_mass=1.0, object_mass=0.3, side_radius=1.0, spin_factor=1.0, zeta0=0.7, zeta_dot0=0.0, softening=0.03)
PAIR = (PlateVortex(id="p", u=0.6, v=0.0, strength=1.0), PlateVortex(id="m", u=-0.5, v=0.4, strength=-0.8))


class Dynamics(unittest.TestCase):
    def test_energy_error_is_second_order_and_spin_conserved(self):
        a = K.run_isosceles(dt=0.002, steps=10000, record_every=1, **BASE)
        b = K.run_isosceles(dt=0.001, steps=20000, record_every=1, **BASE)
        self.assertLess(a["max_e"], 1e-5)
        self.assertTrue(3.5 < a["max_e"] / b["max_e"] < 4.5, a["max_e"] / b["max_e"])
        self.assertLess(a["max_l"], 1e-9)

    def test_mirror_symmetry_holds(self):
        out = K.run_isosceles(dt=0.002, steps=10000, record_every=10, **BASE)
        self.assertLess(out["max_mirror"], 1e-9)
        self.assertTrue(all(c["radial_offset"] < 1e-9 for c in out["crossings"]))

    def test_time_reversal(self):
        eps2 = BASE["softening"] ** 2
        pos, vel, m = K.initial_state(*(BASE[k] for k in ("side_mass", "object_mass", "side_radius", "spin_factor", "zeta0", "zeta_dot0")))
        start = [p[:] for p in pos]
        acc = K.accelerations(pos, m, eps2)
        for _ in range(4000):
            acc = K.verlet_step(pos, vel, m, acc, 0.002, eps2)
        vel = [[-x for x in v] for v in vel]
        acc = K.accelerations(pos, m, eps2)
        for _ in range(4000):
            acc = K.verlet_step(pos, vel, m, acc, 0.002, eps2)
        self.assertLess(np.max(np.abs(np.array(pos) - np.array(start))), 1e-8)

    def test_crossings_alternate_and_interpolate(self):
        out = K.run_isosceles(dt=0.002, steps=15000, record_every=50, **BASE)
        dirs = [c["direction"] for c in out["crossings"]]
        self.assertGreater(len(dirs), 3)
        self.assertEqual(dirs[0], -1)  # starts on the + side
        self.assertTrue(all(a == -b for a, b in zip(dirs, dirs[1:])))
        t, r = out["times"], out["plate"]
        c = out["crossings"][0]
        i = int(np.searchsorted(t, c["t"]))
        self.assertTrue(r[i - 1, 5] > 0 >= r[i, 5] or r[i - 1, 5] >= 0 > r[i, 5])

    def test_phase_is_unwrapped_and_inertial(self):
        out = K.run_isosceles(dt=0.002, steps=20000, record_every=5, **BASE)
        ph = out["plate"][:, 1]
        self.assertGreater(ph[-1], 2 * math.pi)  # several turns, not wrapped
        self.assertTrue(np.all(np.diff(ph) > 0))

    def test_escape_is_reported(self):
        out = K.run_isosceles(dt=0.002, steps=20000, record_every=50, **{**BASE, "zeta_dot0": 6.0})
        self.assertEqual(out["status"], "escaped")


class Service(unittest.TestCase):
    def setUp(self):
        self.service, self.store, self.broker = build_numpy_plate()

    def test_mass_event_continues_without_reset(self):
        req = PlateRunRequest(plate_id="pa", steps=10000, record_every=10,
                              mass_events=(ObjectMassEvent(t=10.0, object_mass=0.6, cause="test"),))
        run = self.service.run(req)
        t = self.store.get(run.times)
        m = self.store.get(run.masses)
        self.assertEqual(run.mass_events_applied, (10.0,))
        self.assertTrue(np.all(np.diff(t) > 0))
        self.assertEqual(sorted(set(np.round(m[:, 2], 6))), [0.3, 0.6])
        self.assertAlmostEqual(t[-1], 20.0, places=6)
        com = (m[:, :, None] * self.store.get(run.positions)).sum(1) / m.sum(1)[:, None]
        self.assertLess(np.abs(com).max(), 1e-12)

    def test_publishes_every_crossing_then_summary(self):
        run = self.service.run(PlateRunRequest(plate_id="pa", object_id="o", steps=8000))
        log = self.broker.replay("plate/pa/#")
        self.assertEqual(sum(e.kind == "plate.crossing" for e in log), len(run.crossings))
        self.assertEqual(log[-1].kind, "plate.run")
        self.assertTrue(all(e.epistemic_status == "simulated" for e in log))
        self.assertEqual(log[-1].payload["plate_sha256"], run.plate.sha256)
        self.service.run(PlateRunRequest(plate_id="pa", object_id="o", steps=8000))
        self.assertEqual(len(self.broker.replay("plate/pa/#")), len(log))  # identical rerun is idempotent

    def test_request_rules(self):
        with self.assertRaises(ValueError):
            IsoscelesParams(zeta0=0)
        with self.assertRaises(ValueError):
            PlateRunRequest(plate_id="p", steps=100, mass_events=(ObjectMassEvent(t=5.0, object_mass=1, cause="late"),))
        with self.assertRaises(ValueError):
            PlateRunRequest(plate_id="p", vortices=(PAIR[0], PAIR[0]))


class Field(unittest.TestCase):
    def test_jacobian_matches_finite_difference_in_both_frames(self):
        vs = np.array([[0.6, 0.0, 1.0], [-0.5, 0.4, -0.8]])
        x = np.array([[0.1, 0.2], [0.9, -0.3], [-0.4, 0.5]])
        h = 1e-6
        for frame, om, ph in (("plate", 0.0, 0.0), ("inertial", 0.8, 0.7)):
            _, jac = K.field_in_frame(x, vs, 0.09, frame, om, ph)
            for j in range(2):
                dx = np.zeros(2); dx[j] = h
                fd = (K.field_in_frame(x + dx, vs, 0.09, frame, om, ph)[0] - K.field_in_frame(x - dx, vs, 0.09, frame, om, ph)[0]) / (2 * h)
                np.testing.assert_allclose(jac[:, :, j], fd, atol=1e-7)

    def test_inertial_is_rotated_plate_field_plus_spin(self):
        vs = np.array([[0.6, 0.0, 1.0]])
        R = np.array([[math.cos(0.7), -math.sin(0.7)], [math.sin(0.7), math.cos(0.7)]])
        x = np.array([[0.3, 0.1]])
        vi, _ = K.field_in_frame(x, vs, 0.09, "inertial", 0.0, 0.7)
        vp, _ = K.plate_field(x @ R, vs, 0.09)
        np.testing.assert_allclose(vi, vp @ R.T)

    def test_arc_bound_dominates_dense_samples(self):
        vs = np.array([[0.6, 0.0, 1.0], [-0.5, 0.4, -0.8], [0.2, 0.25, 0.5]])
        for frame, om, ph in (("plate", 0.0, 0.0), ("inertial", 1.3, 0.4)):
            for center, radius in (((0.6, 0.0), 0.3), ((0.0, 0.0), 1.0), ((0.1, 0.1), 0.2)):
                _, phi, bound = K.ring_samples_and_bounds(vs, 0.09, center, radius, 16, frame, om, ph)
                ends = np.r_[phi[1:], phi[0] + 2 * math.pi]
                for e in range(16):
                    s = np.linspace(phi[e], ends[e], 200)
                    pts = np.c_[center[0] + radius * np.cos(s), center[1] + radius * np.sin(s)]
                    _, jac = K.field_in_frame(pts, vs, 0.09, frame, om, ph)
                    tangent = np.c_[-np.sin(s), np.cos(s)]
                    dds = np.linalg.norm(np.einsum("kij,kj->ki", jac, tangent), axis=1)
                    self.assertLessEqual(dds.max(), bound[e] * (1 + 1e-12))

    def test_point_arc_distance(self):
        self.assertAlmostEqual(K.point_arc_distance((0, 0), (0, 0), 1.0, 0, 1), 1.0)
        self.assertAlmostEqual(K.point_arc_distance((2, 0), (0, 0), 1.0, -0.1, 0.1), 1.0)
        self.assertAlmostEqual(K.point_arc_distance((-2, 0), (0, 0), 1.0, -0.1, 0.1), math.hypot(-2 - math.cos(0.1), math.sin(0.1)))

    def test_service_field_sampling(self):
        service, store, _ = build_numpy_plate()
        pts = put_points(store, [[0.1, 0.2], [0.5, 0.5]])
        res = service.sample_field(PlateFieldRequest(vortices=PAIR, points=pts))
        self.assertEqual(store.get(res.jacobian).shape, (2, 2, 2))
        with self.assertRaises(ValueError):
            PlateFieldRequest(vortices=PAIR, points=pts, omega=1.0)


class Winding(unittest.TestCase):
    def setUp(self):
        self.service, _, _ = build_numpy_plate()

    def w(self, **kw):
        return self.service.ring_winding(RingWindingRequest(vortices=PAIR, **kw))

    def test_single_vortex_certifies_plus_one(self):
        r = self.w(center=(0.6, 0.0), radius=0.3)
        self.assertEqual((r.status, r.certified_index, r.winding_valid), ("certified", 1, True))
        self.assertIn("analytic whole-arc bound", r.bound_provenance)

    def test_negative_vortex_still_index_plus_one(self):
        r = self.w(center=(-0.5, 0.4), radius=0.25)
        self.assertEqual((r.status, r.certified_index), ("certified", 1))  # index is not circulation sign

    def test_pair_and_empty_rings(self):
        both = self.service.ring_winding(RingWindingRequest(
            vortices=(PlateVortex(id="a", u=0.2, v=0, strength=1), PlateVortex(id="b", u=-0.2, v=0, strength=-1)),
            center=(0.0, 0.0), radius=0.8, samples=512))
        self.assertEqual(both.status, "certified")
        # Poincare-Hopf: two regularised cores, each index +1 whatever the spin sign; no saddle between opposite spins.
        self.assertEqual(both.certified_index, 2)
        empty = self.w(center=(0.0, -1.2), radius=0.3)
        self.assertEqual((empty.status, empty.certified_index), ("certified", 0))

    def test_undersampled_ring_is_sampled_only(self):
        r = self.w(center=(0.6, 0.0), radius=0.3, samples=4)
        self.assertEqual((r.status, r.sampled_index, r.winding_valid), ("sampled_only", 1, False))

    def test_inertial_spin_dominated_ring(self):
        r = self.w(center=(0.0, 0.0), radius=1.5, samples=1024, frame="inertial", omega=3.0, phase=0.4)
        self.assertEqual((r.status, r.certified_index), ("certified", 1))

    def test_ring_must_lie_on_plate(self):
        with self.assertRaises(ValueError):
            RingWindingRequest(vortices=PAIR, center=(1.5, 0), radius=0.5)


class Docs(unittest.TestCase):
    def test_every_field_described(self):
        for m in PL.CONTRACTS:
            for name, f in m.model_fields.items():
                self.assertTrue(f.description, f"{m.__name__}.{name}")

    def test_design_page_doctest(self):
        self.assertEqual(doctest.testfile(str(ROOT / "docs/pipelines/PLATE_ISOSCELES.md"), module_relative=False).failed, 0)


if __name__ == "__main__":
    unittest.main()
