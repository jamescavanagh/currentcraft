"""Event-chain sequence and replay tests over the two-subsystem phase fixture (docs/pipelines/PHASE_NUCLEATION.md)."""
import doctest
import json
import random
import sys
import unittest
from datetime import timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from app.application import phase as PH  # noqa: E402
from app.application.phase import chain as C  # noqa: E402

FIX = ROOT / "tests" / "fixtures" / "phase" / "two_subsystems.synthetic.json"
CHAIN = "a.install@r1/simulation"


def load():
    return [PH.PhaseTransitionEvent(**e) for e in json.loads(FIX.read_text())["events"]]


def edit(e, **kw):
    data = e.model_dump()
    data.update(kw)
    return PH.PhaseTransitionEvent(**data)


class EventChains(unittest.TestCase):
    def setUp(self):
        self.events = load()
        self.by_seq = {e.sequence: e for e in self.events}

    def issues(self, events):
        return PH.chain_issues(events)

    def test_fixture_chain_replays_to_accepted(self):
        self.assertEqual(self.issues(self.events), ())
        ((ref, trace, state, length, digest),) = PH.replay_chains(self.events)
        self.assertEqual((ref, trace, state, length), ("a.install@r1", "simulation", "accepted", 8))
        self.assertRegex(digest, r"^[0-9a-f]{64}$")
        self.assertIn(("executing", "conditional"), [(e.prior_state, e.next_state) for e in self.events])  # rework replays

    def test_replay_ignores_input_order(self):
        expected = PH.replay_chains(self.events)
        for seed in range(5):
            shuffled = list(self.events)
            random.Random(seed).shuffle(shuffled)
            self.assertEqual(PH.replay_chains(shuffled), expected)

    def test_exact_retries_are_noops(self):
        self.assertEqual(PH.replay_chains(self.events + self.events), PH.replay_chains(self.events))

    def test_retry_under_same_key_and_input_keeps_the_stored_event(self):
        retry = edit(self.by_seq[7], event_id="ev.a.install.7.retry", occurred_at=self.by_seq[7].occurred_at + timedelta(minutes=5))
        self.assertEqual(self.issues(self.events + [retry]), ())
        self.assertEqual(PH.replay_chains(self.events + [retry]), PH.replay_chains(self.events))

    def test_changed_input_under_same_key_is_a_conflict(self):
        changed = edit(self.by_seq[3], event_id="ev.a.install.3b", input_digest="f" * 64,
                       occurred_at=self.by_seq[3].occurred_at + timedelta(minutes=1))
        self.assertEqual(self.issues(self.events + [changed]), ((CHAIN, "ev.a.install.3b", "key_conflict"),))
        with self.assertRaises(ValueError):
            PH.replay_chains(self.events + [changed])

    def test_reused_event_id_is_a_conflict(self):
        reused = edit(self.by_seq[3], idempotency_key="k.other", input_digest="e" * 64,
                      occurred_at=self.by_seq[3].occurred_at + timedelta(minutes=1))
        self.assertIn((CHAIN, "ev.a.install.3", "event_id_conflict"), self.issues(self.events + [reused]))

    def test_gap(self):
        events = [e for e in self.events if e.sequence != 3]
        self.assertEqual(self.issues(events), ((CHAIN, "ev.a.install.4", "sequence_gap"),))
        with self.assertRaises(ValueError):
            PH.replay_chains(events)

    def test_fork(self):
        rival = edit(self.by_seq[2], event_id="ev.a.install.2b", idempotency_key="k.a.install.2b", input_digest="b" * 64,
                     next_state="possible")
        self.assertEqual(self.issues(self.events + [rival]), (
            (CHAIN, "ev.a.install.2", "sequence_fork"), (CHAIN, "ev.a.install.2b", "sequence_fork")))

    def test_state_mismatch(self):
        events = [edit(e, prior_state="possible", next_state="conditional") if e.sequence == 5 else e for e in self.events]
        found = self.issues(events)
        self.assertIn((CHAIN, "ev.a.install.5", "state_mismatch"), found)
        self.assertIn((CHAIN, "ev.a.install.6", "state_mismatch"), found)  # seq 6 expects ready, not conditional

    def test_time_regression(self):
        events = [edit(e, occurred_at=self.by_seq[4].occurred_at - timedelta(hours=1)) if e.sequence == 5 else e
                  for e in self.events]
        self.assertEqual(self.issues(events), ((CHAIN, "ev.a.install.5", "time_regression"),))

    def test_missing_creation(self):
        events = [e for e in self.events if e.sequence != 0]
        self.assertEqual(self.issues(events), ((CHAIN, "ev.a.install.1", "missing_creation"),))

    def test_traces_are_separate_chains(self):
        created = edit(self.by_seq[0], event_id="gov.a.install.0", idempotency_key="k.gov.a.install.0", trace="governance",
                       input_digest="9" * 64)
        rows = PH.replay_chains(self.events + [created])
        self.assertEqual([(r[0], r[1], r[2], r[3]) for r in rows], [
            ("a.install@r1", "governance", "possible", 1), ("a.install@r1", "simulation", "accepted", 8)])

    def test_digest_tracks_content(self):
        base = PH.replay_chains(self.events)[0][4]
        changed = [edit(e, transition_policy_version="phase-policy/2") if e.sequence == 7 else e for e in self.events]
        self.assertNotEqual(PH.replay_chains(changed)[0][4], base)
        self.assertEqual(PH.chain_digest(reversed(self.events)), base)

    def test_issue_report_is_deterministic(self):
        events = [e for e in self.events if e.sequence not in (0, 3)]
        expected = self.issues(events)
        self.assertEqual(self.issues(list(reversed(events))), expected)
        self.assertTrue(all(issue in PH.CHAIN_ISSUES for _, _, issue in expected))

    def test_doctests(self):
        self.assertEqual(doctest.testmod(C).failed, 0)


if __name__ == "__main__":
    unittest.main()
