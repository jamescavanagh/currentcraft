import doctest
import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from app.application import messaging as MS  # noqa: E402
from app.application.messaging import EventEnvelope, HandoffError, HandoffRouter, Route, make_event, topic_matches  # noqa: E402
from app.application.process import AuthorityRef, CapabilityBinding, ObjectIncidence, ProcessExecution, ProcessType  # noqa: E402
from app.infrastructure.messaging import InMemoryBroker  # noqa: E402

WHEN = datetime(2026, 11, 12, 9, tzinfo=timezone.utc)


def crossing(plate="a", obj="o1", direction=-1, t=1.0, index=0):
    return make_event(topic=f"plate/{plate}/crossing", kind="plate.crossing", source=plate, epistemic_status="simulated",
                      sim_time=t, payload={"plate_id": plate, "object_id": obj, "direction": direction, "index": index})


def gate_exec(obj="o1", decision="release", **kw):
    g = ProcessType(code="gate", name="Gate", function_classes=("control",))
    extra = dict(verification_evidence=("ev",), authority=AuthorityRef(holder_role="r", scope="release")) if decision == "release" else {}
    extra.update(kw)
    return ProcessExecution(execution_id="g:1", process=g, stage="S", occurred_at=extra.pop("occurred_at", WHEN), decision=decision,
                            incidence=(ObjectIncidence(object_id=obj, effect="checks"), ObjectIncidence(object_id="ev", effect="reads")),
                            executed_by=(CapabilityBinding(resource_id="res", resource_role="coordinator"),), **extra)


class Envelope(unittest.TestCase):
    def test_content_hash_and_tamper(self):
        e = crossing()
        self.assertEqual(e.event_id, crossing().event_id)
        with self.assertRaisesRegex(ValueError, "content hash"):
            EventEnvelope(**{**e.model_dump(), "payload": {"object_id": "other"}})

    def test_status_timestamp_rules(self):
        with self.assertRaisesRegex(ValueError, "occurred_at"):
            make_event(topic="x/y", kind="iot.reading", source="d", epistemic_status="computed")
        with self.assertRaisesRegex(ValueError, "sim_time"):
            make_event(topic="x/y", kind="plate.run", source="p", epistemic_status="simulated")

    def test_topics(self):
        with self.assertRaises(ValueError):
            make_event(topic="plate/+/x", kind="plate.run", source="p", epistemic_status="simulated", sim_time=0)
        self.assertTrue(topic_matches("#", "a/b/c"))
        self.assertTrue(topic_matches("a/+/c", "a/b/c"))
        self.assertFalse(topic_matches("a/+/c", "a/b/d"))
        self.assertTrue(topic_matches("a/#", "a"))


class Broker(unittest.TestCase):
    def test_idempotent_replay_and_offsets(self):
        b = InMemoryBroker()
        self.assertTrue(b.publish(crossing()))
        self.assertFalse(b.publish(crossing()))
        b.publish(crossing(plate="b"))
        self.assertEqual(len(b.replay()), 2)
        self.assertEqual(len(b.replay("plate/b/#")), 1)
        self.assertEqual(len(b.replay(from_offset=1)), 1)

    def test_fifo_for_handler_published_events(self):
        b, seen = InMemoryBroker(), []
        b.subscribe("plate/a/crossing", lambda e: b.publish(crossing(plate="b")))
        b.subscribe("#", lambda e: seen.append(e.topic))
        b.publish(crossing())
        self.assertEqual(seen, ["plate/a/crossing", "plate/b/crossing"])

    def test_failing_handler_goes_to_dead_letters(self):
        b, seen = InMemoryBroker(), []
        b.subscribe("#", lambda e: 1 / 0)
        b.subscribe("#", lambda e: seen.append(e))
        b.publish(crossing())
        self.assertEqual(len(seen), 1)
        self.assertEqual(len(b.dead_letters), 1)
        self.assertIn("ZeroDivisionError", b.dead_letters[0][2])

    def test_unsubscribe_and_bad_pattern(self):
        b, seen = InMemoryBroker(), []
        sid = b.subscribe("#", seen.append)
        b.unsubscribe(sid)
        b.publish(crossing())
        self.assertEqual(seen, [])
        with self.assertRaises(ValueError):
            b.subscribe("a/#/b", seen.append)


class Router(unittest.TestCase):
    def setUp(self):
        self.b = InMemoryBroker()
        self.r = HandoffRouter(self.b, routes=(Route(from_plate="a", to_plate="b", direction=-1),))

    def test_one_pending_candidate_per_object(self):
        for i, d in enumerate((-1, 1, -1, -1)):
            self.b.publish(crossing(direction=d, t=float(i), index=i))
        self.assertEqual(len(self.r.pending()), 1)
        self.assertEqual(self.r.pending()[0].payload["status"], "candidate")
        self.assertEqual(self.r.pending()[0].causation_id, self.b.replay("plate/a/crossing")[0].event_id)

    def test_direction_filter(self):
        self.b.publish(crossing(direction=1))
        self.assertEqual(self.r.pending(), ())

    def test_release_resolves_and_reopens(self):
        self.b.publish(crossing())
        cand = self.r.pending()[0]
        d = self.r.decide(cand.event_id, gate_exec())
        self.assertEqual((d.kind, d.epistemic_status, d.causation_id), ("gate.decision", "computed", cand.event_id))
        self.assertEqual(self.r.pending(), ())
        self.b.publish(crossing(t=9.0, index=9))
        self.assertEqual(len(self.r.pending()), 1)

    def test_decide_guards(self):
        self.b.publish(crossing())
        cand = self.r.pending()[0]
        with self.assertRaisesRegex(HandoffError, "check or transfer"):
            self.r.decide(cand.event_id, gate_exec(obj="other"))
        with self.assertRaisesRegex(HandoffError, "timestamp"):
            self.r.decide(cand.event_id, gate_exec(decision="return", occurred_at=None))
        with self.assertRaisesRegex(HandoffError, "unknown"):
            self.r.decide("0" * 64, gate_exec())
        self.assertEqual(self.r.decide(cand.event_id, gate_exec(decision="return")).payload["decision"], "return")


class Docs(unittest.TestCase):
    def test_every_field_described(self):
        for m in MS.CONTRACTS:
            for name, f in m.model_fields.items():
                self.assertTrue(f.description, f"{m.__name__}.{name}")

    def test_doctests(self):
        from app.application.messaging import contracts
        self.assertEqual(doctest.testmod(contracts).failed, 0)
        self.assertEqual(doctest.testfile(str(ROOT / "docs/architecture/MESSAGE_BROKER.md"), module_relative=False).failed, 0)


if __name__ == "__main__":
    unittest.main()
