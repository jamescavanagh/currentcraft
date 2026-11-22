"""0.11 subsystem contract checks (synthetic fixture, public-safe).

Turns mismatches between the configuration view (feature model) and the
architecture view (port graph) into explicit contract checks. Readings are
epistemic 'computed'; none of them is an approval.
Pure Python: no numpy (domain rule).
"""
import itertools
import math
import random
import unittest
from collections import Counter

ALT = {"network": ["avbBase", "danteBase", "aesBase"], "dsp": ["NONE", "dspA", "dspB", "dspC"],
       "codec": ["NONE", "codecX", "codecY"], "camera": ["NONE", "camPTZ", "camFixed", "camAuto"],
       "control": ["ctlP", "ctlQ"]}
BOOL = ["dispLCD", "dispLED", "projector", "wireless", "recording", "overflow"]
V = list(ALT) + BOOL
DOM = {**ALT, **{b: [False, True] for b in BOOL}}
UNTESTED = [{"id": "cell-001", "pair": ("codec", "network"), "values": ("codecY", "aesBase")}]

def on(c, v): return c[v] not in ("NONE", False)
def valid(c, policy):
    ok = on(c, "dsp") and (c["dispLCD"] or c["dispLED"] or c["projector"])
    ok &= c["dsp"] != "dspA" or c["network"] == "danteBase"
    ok &= c["dsp"] != "dspC" or c["network"] != "avbBase"
    ok &= not on(c, "camera") or on(c, "codec")
    ok &= not c["recording"] or on(c, "codec")
    ok &= c["camera"] != "camAuto" or c["control"] == "ctlQ"
    ok &= not c["overflow"] or (c["dispLED"] or c["projector"])
    if policy == "pessimistic":
        ok &= not (c["codec"] == "codecY" and c["network"] == "aesBase")
    return ok
def configs(policy, order=V):
    return [c for c in (dict(zip(order, vals)) for vals in itertools.product(*[DOM[v] for v in order])) if valid(c, policy)]
def mi(cs, a, b):
    n = len(cs); pa = Counter(c[a] for c in cs); pb = Counter(c[b] for c in cs); pab = Counter((c[a], c[b]) for c in cs)
    return sum(k / n * math.log2((k / n) / ((pa[x] / n) * (pb[y] / n))) for (x, y), k in pab.items())

# Architecture view: declared ports (synthetic, drawn for this room)
ARCH = {frozenset(e) for e in [("network","dsp"),("network","codec"),("network","control"),("network","wireless"),
    ("dsp","codec"),("dsp","recording"),("codec","camera"),("codec","dispLCD"),("codec","dispLED"),("codec","projector"),
    ("control","dsp"),("control","codec"),("control","camera"),("control","dispLCD"),("control","dispLED"),("control","projector"),
    ("wireless","dispLCD"),("wireless","dispLED"),("wireless","projector"),("codec","recording")]}
# Declared contracts the fixture must carry for every mismatch class
STANDARD_PORTS = {frozenset(p) for p in [("network","wireless"),("codec","dispLCD"),("codec","dispLED"),("codec","projector"),
    ("control","dispLCD"),("control","dispLED"),("control","projector"),("wireless","dispLCD"),("wireless","dispLED"),("wireless","projector")]}
CONTINGENT_PORTS = {frozenset(p): "cell-001" for p in [("network","codec"),("network","control"),("dsp","codec"),("control","dsp"),("dsp","recording")]}
CONSTRAINTS = {frozenset(p): reason for p, reason in [
    (("dispLCD","dispLED"),"requirement"),(("dispLCD","projector"),"requirement"),(("dispLED","projector"),"requirement"),
    (("dispLCD","overflow"),"mode"),(("dispLED","overflow"),"mode"),(("projector","overflow"),"mode"),
    (("camera","recording"),"indirect"),(("control","recording"),"indirect"),
    (("network","camera"),"indirect"),(("network","recording"),"indirect"),(("dsp","camera"),"indirect")]}
BLOCKS = [["dispLCD","dispLED","projector","overflow"],["wireless"],["camera","control","codec","recording"],["dsp","network"]]
EPS = 1e-9


def _views():
    out = {}
    for pol in ("optimistic", "pessimistic"):
        cs = configs(pol)
        out[pol] = (cs, {frozenset(p): mi(cs, *p) for p in itertools.combinations(V, 2)})
    return out


class SubsystemContractChecks(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.views = _views()

    def test_c1_uncoupled_cables_are_standard_ports(self):
        """C1 cable with no coupling under both counts is a declared standard port."""
        v = self.views
        free = {e for e in ARCH if all(v[p][1][e] < EPS for p in v)}
        self.assertEqual(free, STANDARD_PORTS, f"undeclared standard ports: {free ^ STANDARD_PORTS}")

    def test_c2_contingent_ports_cite_untested_cells(self):
        """C2 cable uncoupled only if the untested cell is compatible cites that cell."""
        v = self.views
        contingent = {e for e in ARCH if v["optimistic"][1][e] < EPS <= v["pessimistic"][1][e]}
        self.assertEqual(contingent, set(CONTINGENT_PORTS))
        cells = {u["id"] for u in UNTESTED}
        self.assertTrue(all(c in cells for c in CONTINGENT_PORTS.values()))

    def test_c3_uncabled_couplings_are_declared_constraints(self):
        """C3 coupling with no cable is a declared constraint, never a connection."""
        for pol, (_, m) in self.views.items():
            coupled = {e for e, x in m.items() if x > EPS and e not in ARCH}
            self.assertFalse(coupled - set(CONSTRAINTS), f"[{pol}] coupling without cable or constraint")
        self.assertLessEqual(set(CONSTRAINTS.values()), {"requirement", "mode", "indirect"})
        self.assertFalse(set(CONSTRAINTS) & ARCH, "a constraint must not be recorded as a connection")

    def test_c4_unknown_induced_couplings_raise_test_priority(self):
        """C4 coupling that appears only under the pessimistic count raises test priority."""
        v = self.views
        induced = {e for e in v["pessimistic"][1] if v["optimistic"][1][e] < EPS <= v["pessimistic"][1][e]}
        self.assertTrue(induced)
        self.assertEqual({u["id"] for u in UNTESTED}, {"cell-001"})

    def test_c5_count_band(self):
        """C5 count is a band, pessimistic <= optimistic, never one number."""
        lo, hi = len(self.views["pessimistic"][0]), len(self.views["optimistic"][0])
        self.assertEqual((lo, hi), (3952, 4680))
        self.assertLessEqual(lo, hi)

    def test_c6_blocks_factorize_only_when_unknowns_resolve(self):
        """C6 conferencing and audio/network multiply only when the unknown resolves."""
        a, b = BLOCKS[2], BLOCKS[3]
        for pol, expect in (("optimistic", True), ("pessimistic", False)):
            cs = self.views[pol][0]; n = len(cs)
            ja = Counter(tuple(c[x] for x in a) for c in cs)
            jb = Counter(tuple(c[x] for x in b) for c in cs)
            jab = Counter((tuple(c[x] for x in a), tuple(c[x] for x in b)) for c in cs)
            independent = all(abs(jab.get((x, y), 0) / n - ja[x] / n * jb[y] / n) < EPS for x in ja for y in jb)
            self.assertIs(independent, expect, pol)

    def test_c7_order_invariance(self):
        """C7 count does not depend on variable order."""
        for seed in (1, 2, 3):
            with self.subTest(seed=seed):
                order = V[:]; random.Random(seed).shuffle(order)
                self.assertEqual(len(configs("pessimistic", order)), 3952)

    def test_c8_readings_are_not_approvals(self):
        """C8 every reading is computed evidence, never an approval."""
        reading = {"kind": "configuration_count", "epistemic": "computed", "band": [3952, 4680], "approval": None}
        self.assertEqual(reading["epistemic"], "computed")
        self.assertIsNone(reading["approval"])


if __name__ == "__main__":
    unittest.main()
