import doctest
import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from app.application import process as P  # noqa: E402
from app.application.process import (AuthorityRef, CapabilityBinding, LifecycleError, ObjectIncidence,  # noqa: E402
                                     ProcessExecution, ProcessType, alive_at_end, derive_object_events)

T = ProcessType(code="make", name="Make", function_classes=("transform",))
C = ProcessType(code="gate", name="Gate", function_classes=("control",))
H = ProcessType(code="stage", name="Stage", function_classes=("hold",))
WHO = (CapabilityBinding(resource_id="res-1", resource_role="maker"),)


def ex(eid, proc, *inc, **kw):
    return ProcessExecution(execution_id=eid, process=proc, stage=kw.pop("stage", "S1"), incidence=inc, executed_by=kw.pop("who", WHO), **kw)


def release(eid="g:1", obj="o1", **kw):
    base = dict(decision="release", verification_evidence=("ev",), authority=AuthorityRef(holder_role="approver", scope="release"))
    base.update(kw)
    return ex(eid, C, ObjectIncidence(object_id=obj, effect="checks", state_after="released"),
              ObjectIncidence(object_id="ev", effect="reads"), **base)


class ProcessRules(unittest.TestCase):
    def test_effects_follow_function_class(self):
        with self.assertRaisesRegex(ValueError, "not allowed"):
            ex("x", T, ObjectIncidence(object_id="o", effect="holds", state_after="staged"))
        ex("x", H, ObjectIncidence(object_id="o", effect="holds", state_after="staged"))

    def test_decision_needs_control(self):
        with self.assertRaisesRegex(ValueError, "control"):
            ex("x", T, ObjectIncidence(object_id="o", effect="reads"), decision="hold")

    def test_release_needs_authority_evidence_and_computed(self):
        release()
        with self.assertRaisesRegex(ValueError, "authority"):
            release(authority=None)
        with self.assertRaisesRegex(ValueError, "evidence"):
            release(verification_evidence=())
        with self.assertRaisesRegex(ValueError, "cannot release"):
            release(epistemic_status="simulated")
        with self.assertRaisesRegex(ValueError, "scope"):
            release(authority=AuthorityRef(holder_role="a", scope="commit_spend"))

    def test_evidence_must_be_looked_at(self):
        with self.assertRaisesRegex(ValueError, "read or checked"):
            release(verification_evidence=("other",))

    def test_entering_a_gate_is_not_approval(self):
        e = ex("g", C, ObjectIncidence(object_id="o", effect="checks"))
        self.assertIsNone(e.decision)
        with self.assertRaisesRegex(ValueError, "only with a gate decision"):
            ex("g", C, ObjectIncidence(object_id="o", effect="checks", state_after="released"))

    def test_objects_are_not_resources(self):
        with self.assertRaisesRegex(ValueError, "resource ids cannot be object ids"):
            ex("x", T, ObjectIncidence(object_id="res-1", effect="produces", state_after="new"))

    def test_one_incidence_per_object(self):
        with self.assertRaisesRegex(ValueError, "one incidence"):
            ex("x", T, ObjectIncidence(object_id="o", effect="reads"), ObjectIncidence(object_id="o", effect="revises", state_after="b"))

    def test_incidence_state_rules(self):
        for bad in (dict(effect="produces"), dict(effect="consumes", state_after="x"), dict(effect="revises"),
                    dict(effect="reads", state_after="x")):
            with self.assertRaises(ValueError):
                ObjectIncidence(object_id="o", **bad)

    def test_participation_is_a_projection(self):
        e = ex("p:1", T, ObjectIncidence(object_id="o", effect="produces", state_after="d"), stage="S2",
               who=(CapabilityBinding(resource_id="r1", resource_role="a"), CapabilityBinding(resource_id="r2", resource_role="b")))
        self.assertEqual([(p.resource_id, p.process_id, p.stage) for p in e.participation()],
                         [("r1", "p:1", "S2"), ("r2", "p:1", "S2")])


class Lifecycle(unittest.TestCase):
    def test_birth_state_change_death_and_censoring(self):
        chain = (ex("a", T, ObjectIncidence(object_id="redline", effect="produces", state_after="draft"),
                    ObjectIncidence(object_id="config", effect="produces", state_after="v1")),
                 ex("b", T, ObjectIncidence(object_id="config", effect="revises", state_before="v1", state_after="v2")),
                 ex("c", T, ObjectIncidence(object_id="redline", effect="consumes"),
                    ObjectIncidence(object_id="asbuilt", effect="produces", state_after="issued")))
        ev = derive_object_events(chain)
        self.assertEqual([(e.kind, e.object_id) for e in ev],
                         [("birth", "redline"), ("birth", "config"), ("state_change", "config"), ("death", "redline"), ("birth", "asbuilt")])
        self.assertEqual(alive_at_end(ev), ("asbuilt", "config"))

    def test_release_is_a_state_change_not_a_death(self):
        ev = derive_object_events((release(),), preexisting=("o1", "ev"))
        self.assertEqual([(e.kind, e.state) for e in ev], [("state_change", "released")])

    def test_violations(self):
        born = ex("a", T, ObjectIncidence(object_id="o", effect="produces", state_after="d"))
        dead = ex("b", T, ObjectIncidence(object_id="o", effect="consumes"))
        for chain, msg in [((born, born), "already alive"), ((born, dead, dead), "after its death"),
                           ((dead,), "not alive"), ((born, dead, born), "after its death")]:
            with self.assertRaisesRegex(LifecycleError, msg):
                derive_object_events(chain)

    def test_state_before_mismatch(self):
        chain = (ex("a", T, ObjectIncidence(object_id="o", effect="produces", state_after="d")),
                 ex("b", T, ObjectIncidence(object_id="o", effect="revises", state_before="x", state_after="y")))
        with self.assertRaisesRegex(LifecycleError, "expected"):
            derive_object_events(chain)

    def test_timestamps_carry_through(self):
        when = datetime(2026, 11, 12, tzinfo=timezone.utc)
        e = ex("a", T, ObjectIncidence(object_id="o", effect="produces", state_after="d"), occurred_at=when)
        self.assertEqual(derive_object_events((e,))[0].occurred_at, when)


class Docs(unittest.TestCase):
    def test_every_field_described(self):
        for m in P.CONTRACTS:
            for name, f in m.model_fields.items():
                self.assertTrue(f.description, f"{m.__name__}.{name}")

    def test_doctests(self):
        from app.application.process import lifecycle
        self.assertEqual(doctest.testmod(lifecycle).failed, 0)
        self.assertEqual(doctest.testfile(str(ROOT / "docs/domain/PROCESS_FIRST.md"), module_relative=False).failed, 0)


if __name__ == "__main__":
    unittest.main()
