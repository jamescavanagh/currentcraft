"""Synthetic phase-nucleation contracts (currentcraft-phase/v1): rules from docs/pipelines/PHASE_NUCLEATION.md."""
import doctest
import json
import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from pydantic import ValidationError  # noqa: E402

from app.application import phase as PH  # noqa: E402
from app.application.phase import (AcceptanceDecision, LedgerObservation, PhaseReading, PhaseRevision,  # noqa: E402
                                   PhaseTransitionEvent)
from app.application.phase import contracts as C  # noqa: E402
from tests.test_simulation_layering import HEAVY, imports, py_files  # noqa: E402

T0 = datetime(2026, 1, 1, tzinfo=timezone.utc)
D = "a" * 64


def event(**kw):
    base = dict(event_id="e1", idempotency_key="k1", phase_ref="design@r1", sequence=1, prior_state="possible",
                next_state="conditional", input_digest=D, transition_policy_version="1", trace="simulation", occurred_at=T0)
    base.update(kw)
    return PhaseTransitionEvent(**base)


def decision(**kw):
    base = dict(decision_id="d1", phase_ref="design@r1", outcome="accept", scope="Synthetic design phase, subsystem A only.",
                authorized_role="phase_reviewer", authority_ref="auth-1", entry_check_ref="install-entry/1",
                evidence_refs=("rd1",), rationale="Entry criteria met on the cited readings.", decided_at=T0)
    base.update(kw)
    return AcceptanceDecision(**base)


def reading(**kw):
    base = dict(reading_id="rd1", phase_ref="design@r1", kind="measurement", source_id="plate-6406", source_version="t6",
                mapping_digest=D, config_digest=D, method="winding-det-sign/1", tolerances=(("det", 1e-9),),
                coordinates=(1.0, 2.0), validity="valid", run_ref="run-1", observed_at=T0)
    base.update(kw)
    return PhaseReading(**base)


class Revisions(unittest.TestCase):
    def test_ref_and_nucleation(self):
        r = PhaseRevision(phase_id="install", revision_id="r1", subsystem_id="a", ordinal=2, entry_profile_version="install-entry/1",
                          requires_accepted=("design@r1",), nucleated_from="design@r1")
        self.assertEqual(r.ref, "install@r1")

    def test_self_reference_and_nucleation_rules(self):
        with self.assertRaises(ValidationError):
            PhaseRevision(phase_id="p", revision_id="r1", subsystem_id="a", ordinal=1, entry_profile_version="1", requires_accepted=("p@r1",))
        with self.assertRaises(ValidationError):
            PhaseRevision(phase_id="p", revision_id="r1", subsystem_id="a", ordinal=2, entry_profile_version="1", nucleated_from="q@r1")
        with self.assertRaises(ValidationError):
            PhaseRevision(phase_id="p", revision_id="r1", subsystem_id="a", ordinal=2, entry_profile_version="1",
                          requires_accepted=("q@r1", "q@r1"))
        with self.assertRaises(ValidationError):
            PhaseRevision(phase_id="p", revision_id="r1", subsystem_id="a", ordinal=0, entry_profile_version="1")
        with self.assertRaises(ValidationError):
            PhaseRevision(phase_id="p", revision_id="r1", subsystem_id="a", ordinal=1, entry_profile_version="1", requires_accepted=("q",))


class Transitions(unittest.TestCase):
    def test_allowed_table(self):
        for prior, nxt in PH.ALLOWED_TRANSITIONS:
            seq = 0 if prior is None else 1
            needs = nxt in PH.DECISION_STATES
            event(sequence=seq, prior_state=prior, next_state=nxt)
            event(sequence=seq, prior_state=prior, next_state=nxt, trace="governance",
                  decision_ref="d1" if needs else None, evidence_refs=("rd1",) if needs else ())

    def test_disallowed_pairs_and_absorbing_accepted(self):
        allowed = PH.ALLOWED_TRANSITIONS
        for prior in (None,) + PH.PHASE_STATES:
            for nxt in PH.PHASE_STATES:
                if (prior, nxt) in allowed:
                    continue
                with self.assertRaises(ValidationError, msg=f"{prior}->{nxt}"):
                    event(sequence=0 if prior is None else 1, prior_state=prior, next_state=nxt)
        self.assertFalse([p for p in allowed if p[0] == "accepted"])
        self.assertEqual(set(PH.ABSORBING_STATES) | set(PH.TRANSIENT_STATES), set(PH.PHASE_STATES))

    def test_sequence_zero_is_creation_only(self):
        with self.assertRaises(ValidationError):
            event(sequence=0)
        with self.assertRaises(ValidationError):
            event(sequence=1, prior_state=None, next_state="possible")

    def test_simulation_trace_never_carries_a_decision(self):
        with self.assertRaises(ValidationError):
            event(prior_state="executing", next_state="accepted", decision_ref="d1")
        self.assertIsNone(event(prior_state="executing", next_state="accepted").decision_ref)

    def test_governance_requires_decision_and_evidence(self):
        with self.assertRaises(ValidationError):
            event(trace="governance", prior_state="ready", next_state="executing")
        with self.assertRaises(ValidationError):
            event(trace="governance", prior_state="executing", next_state="accepted", decision_ref="d1")
        event(trace="governance", prior_state="ready", next_state="executing", decision_ref="d1")
        event(trace="governance", prior_state="ready", next_state="conditional")

    def test_replay(self):
        e = event()
        self.assertEqual(e.replay_against(None), "new")
        self.assertEqual(e.replay_against(e), "noop")
        self.assertEqual(e.replay_against(e.model_copy(update={"input_digest": "b" * 64})), "conflict")
        with self.assertRaises(ValueError):
            e.replay_against(e.model_copy(update={"idempotency_key": "k2"}))

    def test_naive_time_and_duplicate_evidence_rejected(self):
        with self.assertRaises(ValidationError):
            event(occurred_at=datetime(2026, 1, 1))
        with self.assertRaises(ValidationError):
            event(evidence_refs=("rd1", "rd1"))


class Decisions(unittest.TestCase):
    def test_accept_needs_evidence_and_records_human(self):
        self.assertEqual(decision().recorded_by, "human")
        with self.assertRaises(ValidationError):
            decision(evidence_refs=())
        decision(outcome="hold", evidence_refs=())
        decision(outcome="return", evidence_refs=())
        with self.assertRaises(ValidationError):
            decision(recorded_by="model")

    def test_expiry_and_time(self):
        decision(expires_at=T0 + timedelta(days=1))
        with self.assertRaises(ValidationError):
            decision(expires_at=T0)
        with self.assertRaises(ValidationError):
            decision(decided_at=datetime(2026, 1, 1))
        with self.assertRaises(ValidationError):
            decision(conditions=("c", "c"))

    def test_role_not_free_text(self):
        with self.assertRaises(ValidationError):
            decision(authorized_role="A Person Name")


class ReadingsAndLedger(unittest.TestCase):
    def test_validity_states_stay_distinct(self):
        for v in ("valid", "stale", "failed", "unknown", "inaccessible"):
            self.assertEqual(reading(validity=v).validity, v)
        with self.assertRaises(ValidationError):
            reading(validity="ok")

    def test_tolerances(self):
        with self.assertRaises(ValidationError):
            reading(tolerances=(("det", -1.0),))
        with self.assertRaises(ValidationError):
            reading(tolerances=(("det", 1.0), ("det", 2.0)))

    def test_synthetic_only(self):
        with self.assertRaises(ValidationError):
            reading(epistemic_status="observed")
        obs = LedgerObservation(observation_id="o1", subject_ref="inv-syn-1", status="reconciled", source_id="ledger-fixture",
                                source_revision="1", observed_at=T0, related_phase_refs=("closeout@r1",))
        self.assertEqual(obs.epistemic_status, "synthetic_fixture")
        with self.assertRaises(ValidationError):
            LedgerObservation(observation_id="o1", subject_ref="s", status="paid", source_id="x", source_revision="1", observed_at=T0)
        with self.assertRaises(ValidationError):
            LedgerObservation(observation_id="o1", subject_ref="s", status="invoiced", source_id="x", source_revision="1",
                              observed_at=T0, amount=1)

    def test_closed_contracts(self):
        with self.assertRaises(ValidationError):
            reading(approved=True)


class Reference(unittest.TestCase):
    def test_fields_described_and_doctests(self):
        for m in PH.CONTRACTS:
            for n, f in m.model_fields.items():
                self.assertTrue(f.description, f"{m.__name__}.{n}")
            self.assertTrue((m.__doc__ or "").strip(), m.__name__)
        self.assertEqual(doctest.testmod(C).failed, 0)
        self.assertEqual(doctest.testfile(str(ROOT / "docs/pipelines/PHASE_NUCLEATION.md"), module_relative=False).failed, 0)

    def test_generated_schemas_match(self):
        for m in PH.CONTRACTS:
            path = ROOT / "docs" / "contracts" / "schemas" / "agency" / f"{m.__name__}.schema.json"
            self.assertEqual(json.loads(path.read_text()), m.model_json_schema(), m.__name__)
        ref = (ROOT / "docs" / "contracts" / "PHASE_CONTRACTS.md").read_text()
        for m in PH.CONTRACTS:
            self.assertIn(f"## `{m.__name__}`", ref)
        self.assertNotIn("Synthetic phase nucleation", (ROOT / "docs" / "contracts" / "AGENCY_CONTRACTS.md").read_text())

    def test_layering(self):
        files = py_files("application/phase")
        self.assertTrue(files)
        for f in files:
            mods = imports(f)
            self.assertFalse({m for m in mods if m.split(".")[0] in HEAVY}, f.name)
            self.assertFalse({m for m in mods if m.startswith(("app.infrastructure", "infrastructure"))}, f.name)
            self.assertNotIn("arbitrary_types_allowed", f.read_text(encoding="utf-8"), f.name)


if __name__ == "__main__":
    unittest.main()
