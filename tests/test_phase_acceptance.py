"""Predecessor-acceptance checks across the two-subsystem phase fixture (docs/pipelines/PHASE_NUCLEATION.md)."""
import doctest
import json
import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from app.application import phase as PH  # noqa: E402
from app.application.phase import acceptance as A  # noqa: E402

FIX = ROOT / "tests" / "fixtures" / "phase" / "two_subsystems.synthetic.json"
BEFORE = datetime(2026, 1, 6, tzinfo=timezone.utc)   # before any fixture decision
AFTER = datetime(2026, 1, 7, tzinfo=timezone.utc)    # after every fixture decision
DECIDED = datetime(2026, 1, 6, 12, tzinfo=timezone.utc)


def load():
    fx = json.loads(FIX.read_text())
    return ([PH.PhaseRevision(**r) for r in fx["revisions"]], [PH.AcceptanceDecision(**d) for d in fx["decisions"]],
            [PH.PhaseTransitionEvent(**e) for e in fx["events"]])


def decision(base, **kw):
    data = base.model_dump()
    data.update(kw)
    return PH.AcceptanceDecision(**data)


def leave_possible(event_id, phase_ref, at, trace="governance"):
    return PH.PhaseTransitionEvent(event_id=event_id, idempotency_key=f"k.{event_id}", phase_ref=phase_ref, sequence=1,
                                   prior_state="possible", next_state="conditional", input_digest="c" * 64,
                                   transition_policy_version="phase-policy/1", trace=trace, occurred_at=at)


class FixtureAcceptance(unittest.TestCase):
    def setUp(self):
        self.revs, self.decs, self.events = load()
        self.by_id = {d.decision_id: d for d in self.decs}

    def status(self, statuses, succ, pred):
        return {(s, p): st for s, p, st in statuses}[(succ, pred)]

    def test_every_required_predecessor_is_read(self):
        statuses = PH.predecessor_statuses(self.revs, self.decs, AFTER)
        self.assertEqual(len(statuses), sum(len(r.requires_accepted) for r in self.revs))
        self.assertTrue(all(st in PH.PREDECESSOR_STATUSES for _, _, st in statuses))

    def test_fixture_after_decisions(self):
        self.assertEqual(PH.predecessor_statuses(self.revs, self.decs, AFTER), (
            ("a.commission@r1", "a.install@r1", "accepted"),
            ("a.install@r1", "a.design@r1", "accepted"),
            ("b.commission@r1", "a.commission@r1", "accepted"),
            ("b.commission@r1", "b.install@r1", "held"),
            ("b.install@r1", "b.design@r1", "accepted")))
        eligible = PH.eligible_to_leave_possible(self.revs, self.decs, AFTER)
        self.assertNotIn("b.commission@r1", eligible)
        self.assertEqual(len(eligible), 5)

    def test_cross_subsystem_acceptance_does_not_override_a_local_hold(self):
        statuses = PH.predecessor_statuses(self.revs, self.decs, AFTER)
        self.assertEqual(self.status(statuses, "b.commission@r1", "a.commission@r1"), "accepted")
        self.assertEqual(self.status(statuses, "b.commission@r1", "b.install@r1"), "held")

    def test_decisions_are_not_backdated(self):
        self.assertTrue(all(st == "undecided" for _, _, st in PH.predecessor_statuses(self.revs, self.decs, BEFORE)))
        self.assertEqual(PH.eligible_to_leave_possible(self.revs, self.decs, BEFORE), ("a.design@r1", "b.design@r1"))
        self.assertEqual(self.status(PH.predecessor_statuses(self.revs, self.decs, DECIDED), "a.install@r1", "a.design@r1"), "accepted")

    def test_simulated_acceptance_never_counts(self):
        self.assertEqual(self.events[-1].next_state, "accepted")  # the fixture simulates a.install reaching accepted
        decs = [d for d in self.decs if d.decision_id != "dec.a.install"]
        self.assertEqual(self.status(PH.predecessor_statuses(self.revs, decs, AFTER), "a.commission@r1", "a.install@r1"), "undecided")

    def test_hold_then_accept_releases_nothing_but_unblocks(self):
        later = decision(self.by_id["dec.b.install"], decision_id="dec.b.install.2", outcome="accept",
                         decided_at=DECIDED + timedelta(hours=1), scope="Install evidence refreshed.")
        decs = self.decs + [later]
        self.assertIn("b.commission@r1", PH.eligible_to_leave_possible(self.revs, decs, AFTER))
        self.assertNotIn("b.commission@r1", PH.eligible_to_leave_possible(self.revs, decs, DECIDED + timedelta(minutes=30)))

    def test_accept_is_absorbing(self):
        later = decision(self.by_id["dec.a.design"], decision_id="dec.a.design.2", outcome="return", evidence_refs=(),
                         decided_at=DECIDED + timedelta(hours=1))
        statuses = PH.predecessor_statuses(self.revs, self.decs + [later], AFTER)
        self.assertEqual(self.status(statuses, "a.install@r1", "a.design@r1"), "conflict")

    def test_same_time_disagreement_is_a_conflict(self):
        rival = decision(self.by_id["dec.b.design"], decision_id="dec.b.design.rival", outcome="hold")
        statuses = PH.predecessor_statuses(self.revs, self.decs + [rival], AFTER)
        self.assertEqual(self.status(statuses, "b.install@r1", "b.design@r1"), "conflict")

    def test_expiry(self):
        decs = [decision(d, expires_at=DECIDED + timedelta(hours=6)) if d.decision_id == "dec.a.install" else d for d in self.decs]
        self.assertEqual(self.status(PH.predecessor_statuses(self.revs, decs, DECIDED + timedelta(hours=1)), "a.commission@r1", "a.install@r1"), "accepted")
        self.assertEqual(self.status(PH.predecessor_statuses(self.revs, decs, AFTER), "a.commission@r1", "a.install@r1"), "expired")

    def test_acceptance_against_another_successors_check(self):
        decs = [decision(d, entry_check_ref="integration-entry/1") if d.decision_id == "dec.a.commission" else d for d in self.decs]
        statuses = PH.predecessor_statuses(self.revs, decs, AFTER)
        self.assertEqual(self.status(statuses, "b.commission@r1", "a.commission@r1"), "other_entry_check")

    def test_missing_predecessor(self):
        revs = [r for r in self.revs if r.ref != "a.commission@r1"]
        statuses = PH.predecessor_statuses(revs, self.decs, AFTER)
        self.assertEqual(self.status(statuses, "b.commission@r1", "a.commission@r1"), "missing")

    def test_governance_events_read_at_their_own_time(self):
        events = [leave_possible("ev.ok", "a.commission@r1", AFTER),
                  leave_possible("ev.early", "a.install@r1", BEFORE),
                  leave_possible("ev.held", "b.commission@r1", AFTER),
                  leave_possible("ev.sim", "b.commission@r1", AFTER, trace="simulation"),
                  leave_possible("ev.unknown", "c.design@r1", AFTER)]
        self.assertEqual(PH.governance_violations(self.revs, self.decs, self.events + events), (
            ("ev.early", "a.design@r1", "undecided"),
            ("ev.held", "b.install@r1", "held"),
            ("ev.unknown", "c.design@r1", "unknown_revision")))

    def test_naive_time_and_duplicates_rejected(self):
        with self.assertRaises(ValueError):
            PH.predecessor_statuses(self.revs, self.decs, datetime(2026, 1, 7))
        with self.assertRaises(ValueError):
            PH.predecessor_statuses(self.revs + [self.revs[0]], self.decs, AFTER)

    def test_doctests(self):
        self.assertEqual(doctest.testmod(A).failed, 0)


if __name__ == "__main__":
    unittest.main()
