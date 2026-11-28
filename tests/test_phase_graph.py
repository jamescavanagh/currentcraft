"""Two-subsystem phase fixture and cross-phase cycle checks (currentcraft-phase/v1, docs/pipelines/PHASE_NUCLEATION.md)."""
import doctest
import json
import random
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from app.application import phase as PH  # noqa: E402
from app.application.phase import graph as G  # noqa: E402

FIX = ROOT / "tests" / "fixtures" / "phase" / "two_subsystems.synthetic.json"


def load():
    fx = json.loads(FIX.read_text())
    return (fx, [PH.PhaseRevision(**r) for r in fx["revisions"]], [PH.PhaseReading(**r) for r in fx["readings"]],
            [PH.PhaseTransitionEvent(**e) for e in fx["events"]], [PH.AcceptanceDecision(**d) for d in fx["decisions"]],
            [PH.LedgerObservation(**o) for o in fx["ledger_observations"]])


def with_requires(revisions, ref, requires):
    """Rebuild one revision with new forward requirements, through validation (no model_copy shortcut)."""
    out = []
    for r in revisions:
        if r.ref == ref:
            data = r.model_dump()
            data["requires_accepted"] = tuple(requires)
            if data["nucleated_from"] not in data["requires_accepted"]:
                data["nucleated_from"] = None
            r = PH.PhaseRevision(**data)
        out.append(r)
    return out


class Fixture(unittest.TestCase):
    def setUp(self):
        self.fx, self.revs, self.readings, self.events, self.decisions, self.ledger = load()
        self.by_ref = {r.ref: r for r in self.revs}

    def test_shape(self):
        self.assertEqual(self.fx["schema_version"], PH.SCHEMA_VERSION)
        self.assertEqual(sorted({r.subsystem_id for r in self.revs}), ["a", "b"])
        for sub in ("a", "b"):
            self.assertEqual(sorted(r.ordinal for r in self.revs if r.subsystem_id == sub), [1, 2, 3])
        cross = [(p, s) for p, s in PH.forward_edges(self.revs) if self.by_ref[p].subsystem_id != self.by_ref[s].subsystem_id]
        self.assertEqual(cross, [("a.commission@r1", "b.commission@r1")])

    def test_acyclic_and_complete(self):
        self.assertIsNone(PH.find_forward_cycle(self.revs))
        self.assertEqual(PH.check_forward_dependencies(self.revs), ())

    def test_references_resolve(self):
        readings = {r.reading_id for r in self.readings}
        for e in self.events:
            self.assertIn(e.phase_ref, self.by_ref)
            self.assertLessEqual(set(e.evidence_refs), readings)
        for d in self.decisions:
            self.assertIn(d.phase_ref, self.by_ref)
            self.assertLessEqual(set(d.evidence_refs), readings)
        for o in self.ledger:
            self.assertLessEqual(set(o.related_phase_refs), set(self.by_ref))

    def test_rework_loop_is_not_a_dependency_cycle(self):
        chain = sorted(self.events, key=lambda e: e.sequence)
        self.assertEqual([e.sequence for e in chain], list(range(len(chain))))
        for before, after in zip(chain, chain[1:]):
            self.assertEqual(before.next_state, after.prior_state)
        self.assertIn(("executing", "conditional"), [(e.prior_state, e.next_state) for e in chain])
        self.assertEqual(chain[-1].next_state, "accepted")
        self.assertTrue(all(e.trace == "simulation" and e.decision_ref is None for e in chain))
        self.assertIsNone(PH.find_forward_cycle(self.revs))

    def test_governs_links_point_backward_and_stay_out_of_the_forward_graph(self):
        profiles = {r.entry_profile_version: r.ref for r in self.revs}
        forward = set(PH.forward_edges(self.revs))
        for d in self.decisions:
            successor = profiles[d.entry_check_ref]
            # The successor's published check governs the predecessor; as a forward edge it would close a cycle.
            self.assertIn((d.phase_ref, successor), forward)
        self.assertIsNone(PH.find_forward_cycle(self.revs))

    def test_hold_and_ledger_are_independent(self):
        held = [d for d in self.decisions if d.outcome == "hold"]
        self.assertEqual([d.phase_ref for d in held], ["b.install@r1"])
        self.assertFalse([d for d in self.decisions if d.phase_ref == "b.commission@r1"])
        self.assertEqual([o.status for o in self.ledger], ["invoiced"])
        self.assertEqual({o.epistemic_status for o in self.ledger}, {"synthetic_fixture"})


class CrossPhaseCycles(unittest.TestCase):
    def setUp(self):
        _, self.revs, *_ = load()

    def assertCycle(self, revisions, expected):
        self.assertEqual(PH.find_forward_cycle(revisions), expected)
        with self.assertRaisesRegex(ValueError, "forward dependency cycle: " + " -> ".join(expected).replace(".", r"\.")):
            PH.check_forward_dependencies(revisions)

    def test_cycle_through_the_cross_subsystem_edge(self):
        revs = with_requires(self.revs, "a.design@r1", ["b.commission@r1"])
        self.assertCycle(revs, ("a.commission@r1", "b.commission@r1", "a.design@r1", "a.install@r1", "a.commission@r1"))

    def test_cycle_inside_one_subsystem(self):
        revs = with_requires(self.revs, "b.design@r1", ["b.install@r1"])
        self.assertCycle(revs, ("b.design@r1", "b.install@r1", "b.design@r1"))

    def test_cycle_spanning_both_subsystems(self):
        revs = with_requires(self.revs, "a.install@r1", ["a.design@r1", "b.install@r1"])
        revs = with_requires(revs, "b.install@r1", ["a.commission@r1", "b.design@r1"])
        self.assertCycle(revs, ("a.commission@r1", "b.install@r1", "a.install@r1", "a.commission@r1"))

    def test_cycle_report_is_order_independent(self):
        revs = with_requires(self.revs, "a.design@r1", ["b.commission@r1"])
        expected = PH.find_forward_cycle(revs)
        rng = random.Random(6406)
        for _ in range(20):
            shuffled = list(revs)
            rng.shuffle(shuffled)
            self.assertEqual(PH.find_forward_cycle(shuffled), expected)

    def test_new_revision_does_not_create_a_cycle(self):
        r2 = PH.PhaseRevision(phase_id="a.install", revision_id="r2", subsystem_id="a", ordinal=2, entry_profile_version="a.install-entry/2",
                              requires_accepted=("a.design@r1",), nucleated_from="a.design@r1")
        self.assertEqual(PH.check_forward_dependencies(self.revs + [r2]), ())

    def test_missing_predecessor_is_a_gap_not_a_cycle(self):
        revs = [r for r in self.revs if r.ref != "a.install@r1"]
        self.assertIsNone(PH.find_forward_cycle(revs))
        self.assertEqual(PH.check_forward_dependencies(revs), (("a.commission@r1", "a.install@r1"),))

    def test_duplicate_revision_rejected(self):
        with self.assertRaisesRegex(ValueError, "duplicate phase revision a.design@r1"):
            PH.check_forward_dependencies(self.revs + [self.revs[0]])

    def test_doctests(self):
        self.assertEqual(doctest.testmod(G).failed, 0)


if __name__ == "__main__":
    unittest.main()
