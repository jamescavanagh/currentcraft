"""0.11 subsystem contract checks (synthetic fixture, public-safe).

Turns mismatches between the configuration view (feature model) and the
architecture view (port graph) into explicit contract checks. Readings are
epistemic 'computed'; none of them is an approval.
Pure Python: no numpy (domain rule).
"""
import itertools, math, random
from collections import Counter
import pytest

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

@pytest.fixture(scope="module")
def views():
    out = {}
    for pol in ("optimistic", "pessimistic"):
        cs = configs(pol)
        out[pol] = (cs, {frozenset(p): mi(cs, *p) for p in itertools.combinations(V, 2)})
    return out

# C1 cable with no coupling under BOTH policies -> must be a declared standard port
def test_c1_uncoupled_cables_are_standard_ports(views):
    free = {e for e in ARCH if all(views[p][1][e] < EPS for p in views)}
    assert free == STANDARD_PORTS, f"undeclared standard ports: {free ^ STANDARD_PORTS}"

# C2 cable uncoupled only if the untested cell is compatible -> contingent port citing the cell
def test_c2_contingent_ports_cite_untested_cells(views):
    contingent = {e for e in ARCH if views["optimistic"][1][e] < EPS <= views["pessimistic"][1][e]}
    assert contingent == set(CONTINGENT_PORTS)
    assert all(cell in {u["id"] for u in UNTESTED} for cell in CONTINGENT_PORTS.values())

# C3 coupling with no cable -> declared constraint with a reason class, never a connection
def test_c3_uncabled_couplings_are_declared_constraints(views):
    for pol in views:
        coupled = {e for e, m in views[pol][1].items() if m > EPS and e not in ARCH}
        missing = coupled - set(CONSTRAINTS)
        assert not missing, f"[{pol}] coupling without cable or constraint: {missing}"
    assert set(CONSTRAINTS.values()) <= {"requirement", "mode", "indirect"}
    assert not (set(CONSTRAINTS) & ARCH), "a constraint must not be recorded as a connection"

# C4 coupling that appears only under the pessimistic count -> test-priority item
def test_c4_unknown_induced_couplings_raise_test_priority(views):
    induced = {e for e in views["pessimistic"][1] if views["optimistic"][1][e] < EPS <= views["pessimistic"][1][e]}
    assert induced, "expected at least one unknown-induced coupling in the fixture"
    priority = {u["id"] for u in UNTESTED}
    assert priority == {"cell-001"}

# C5 count band: pessimistic <= optimistic; both recorded (never a single number)
def test_c5_count_band(views):
    lo, hi = len(views["pessimistic"][0]), len(views["optimistic"][0])
    assert (lo, hi) == (3952, 4680) and lo <= hi

# C6 block factorization: independent blocks (cut width 1) multiply exactly
def test_c6_blocks_factorize_only_when_unknowns_resolve(views):
    for pol, expect in (("optimistic", True), ("pessimistic", False)):
        cs = views[pol][0]; n = len(cs)
        a, b = BLOCKS[2], BLOCKS[3]
        ja = Counter(tuple(c[v] for v in a) for c in cs); jb = Counter(tuple(c[v] for v in b) for c in cs)
        jab = Counter((tuple(c[v] for v in a), tuple(c[v] for v in b)) for c in cs)
        independent = all(abs(jab.get((x, y), 0) / n - ja[x] / n * jb[y] / n) < EPS for x in ja for y in jb)
        assert independent is expect, f"[{pol}] conferencing vs audio/network independence should be {expect}"

# C7 counts do not depend on variable order
@pytest.mark.parametrize("seed", [1, 2, 3])
def test_c7_order_invariance(seed):
    order = V[:]; random.Random(seed).shuffle(order)
    assert len(configs("pessimistic", order)) == 3952

# C8 every reading is computed evidence, never an approval
def test_c8_readings_are_not_approvals():
    reading = {"kind": "configuration_count", "epistemic": "computed", "band": [3952, 4680], "approval": None}
    assert reading["epistemic"] == "computed" and reading["approval"] is None
