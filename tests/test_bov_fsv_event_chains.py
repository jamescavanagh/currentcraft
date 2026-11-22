"""DRAFT acceptance: BOV-to-FSV event chains (Open-edi business view to functional service view).

Rule under test: information exchange and commitment exchange stay separate. Of the
datamesh-event/v1 kinds, only `gate.decision` is commitment exchange, and only a computed
ProcessExecution with decision, authority and verification evidence can produce it.
Everything else (scenario, candidate, intake, storage, readings) is information exchange.

Part A runs against datamesh-event/v1 today. Part B is the proposed datamesh-event/v2
(agent.interaction, recorded_at, principal_id) and skips until that version exists.
Design notes: private page "ISO/IEC 15944-4 and agent interaction with Currentcraft".
"""
import sys
import typing
import unittest
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / 'src'))

from app.application.messaging import HandoffRouter, Route  # noqa: E402
from app.application.messaging.contracts import EventKind, make_event  # noqa: E402
from app.application.plate import IsoscelesParams, PlateRunRequest  # noqa: E402
from app.application.process import (  # noqa: E402
    AuthorityRef, CapabilityBinding, ObjectIncidence, ProcessExecution, ProcessType)
from app.infrastructure.plate import build_numpy_plate  # noqa: E402

KINDS = set(typing.get_args(EventKind))
COMMITMENT_KINDS = {'gate.decision'}
SCENARIO_KINDS = {'plate.run', 'plate.crossing', 'object.handoff'}
FSV_KINDS = {'raw.item', 'domain.object', 'domain.stored', 'ingest.rejection', 'iot.reading'}
# Release gate that must hold each test as an exit criterion (earliest release that depends on it).
RELEASE_GATES = {
    'test_republishing_is_idempotent': '0.10.0 API/live acceptance',
    'test_kind_partition_is_complete': '0.11.0 evidence baseline',
    'test_computed_event_needs_a_real_timestamp': '0.11.0 evidence baseline',
    'test_replay_rebuilds_candidate_before_decision': '0.11.0 evidence baseline',
    'test_scenario_produces_candidates_only': '0.13.0 expectation grammar',
    'test_agent_interaction_references_snapshot_by_digest': '0.14.0 agency reads',
    'test_two_clocks': '0.14.0 agency reads',
    'test_v1_reads_v2_writes': '0.14.0 agency reads',
    'test_decision_is_computed_and_caused_by_candidate': '0.15.0 agency writes/review',
    'test_only_gate_decision_carries_a_decision': '0.15.0 agency writes/review',
    'test_release_without_authority_is_rejected': '0.15.0 agency writes/review',
    'test_release_without_verification_evidence_is_rejected': '0.15.0 agency writes/review',
    'test_decision_on_a_different_object_is_rejected': '0.15.0 agency writes/review',
    'test_agent_interaction_is_information_exchange': '0.15.0 agency writes/review',
    'test_agent_interaction_names_a_principal': '0.15.0 agency writes/review',
    'test_agent_interaction_cannot_cause_a_decision_alone': '0.15.0 agency writes/review',
}

WHEN = datetime(2026, 11, 21, 9, 0, tzinfo=timezone.utc)
GATE = ProcessType(code='gate', name='Handoff gate', function_classes=('control',))


def chain():
    """Synthetic plate A crosses into plate B; returns broker, router and the candidate."""
    service, _store, broker = build_numpy_plate()
    router = HandoffRouter(broker, routes=(Route(from_plate='plate-a', to_plate='plate-b', direction=-1),))
    service.run(PlateRunRequest(plate_id='plate-a', object_id='obj-1', params=IsoscelesParams(), steps=6000))
    intake = broker.replay('plate/plate-b/intake')
    return broker, router, intake


def release(object_id='obj-1', **overrides):
    fields = dict(
        execution_id='acc:gate:1', process=GATE, stage='S3', occurred_at=WHEN,
        incidence=(ObjectIncidence(object_id=object_id, effect='checks', state_after='released'),
                   ObjectIncidence(object_id='obj-receipt', effect='reads')),
        executed_by=(CapabilityBinding(resource_id='res-approver', resource_role='approver'),),
        decision='release', verification_evidence=('obj-receipt',),
        authority=AuthorityRef(holder_role='handoff-approver', scope='release'))
    fields.update(overrides)
    return ProcessExecution(**fields)


class EventChainV1(unittest.TestCase):
    """Part A: datamesh-event/v1."""

    def test_every_test_has_a_release_gate(self):
        """A new test fails until it is assigned to the release that must hold it."""
        names = {n for c in (EventChainV1, EventChainV2) for n in dir(c) if n.startswith('test_')}
        names.discard('test_every_test_has_a_release_gate')
        self.assertEqual(names, set(RELEASE_GATES))

    def test_kind_partition_is_complete(self):
        """Every v1 kind is classified; a new kind fails until someone places it on one side."""
        classified = COMMITMENT_KINDS | SCENARIO_KINDS | FSV_KINDS | {'hil.label', 'object.lifecycle'}
        self.assertEqual(KINDS, classified)

    def test_scenario_produces_candidates_only(self):
        broker, router, intake = chain()
        self.assertEqual(len(intake), 1)
        self.assertEqual(intake[0].payload['status'], 'candidate')
        self.assertEqual(intake[0].epistemic_status, 'simulated')
        self.assertEqual(broker.replay('gate/#'), ())
        self.assertEqual(len(router.pending()), 1)

    def test_decision_is_computed_and_caused_by_candidate(self):
        _broker, router, intake = chain()
        decision = router.decide(intake[0].event_id, release())
        self.assertEqual(decision.kind, 'gate.decision')
        self.assertEqual(decision.epistemic_status, 'computed')
        self.assertEqual(decision.occurred_at, WHEN)
        self.assertEqual(decision.causation_id, intake[0].event_id)
        self.assertEqual(router.pending(), ())

    def test_only_gate_decision_carries_a_decision(self):
        broker, router, intake = chain()
        router.decide(intake[0].event_id, release())
        for event in broker.replay('#'):
            if 'decision' in event.payload:
                self.assertIn(event.kind, COMMITMENT_KINDS, event.topic)

    def test_release_without_authority_is_rejected(self):
        with self.assertRaises(ValueError):
            release(authority=None)

    def test_release_without_verification_evidence_is_rejected(self):
        with self.assertRaises(ValueError):
            release(verification_evidence=())

    def test_decision_on_a_different_object_is_rejected(self):
        _broker, router, intake = chain()
        with self.assertRaises(Exception):
            router.decide(intake[0].event_id, release(object_id='obj-other'))
        self.assertEqual(len(router.pending()), 1)

    def test_computed_event_needs_a_real_timestamp(self):
        with self.assertRaises(ValueError):
            make_event(topic='gate/x/decision', kind='gate.decision', source='router',
                       epistemic_status='computed', payload={'decision': 'release'})

    def test_republishing_is_idempotent(self):
        a = make_event(topic='raw/p/f/s', kind='raw.item', source='intake', epistemic_status='computed',
                       occurred_at=WHEN, payload={'sha256': '0' * 64})
        b = make_event(topic='raw/p/f/s', kind='raw.item', source='intake', epistemic_status='computed',
                       occurred_at=WHEN, payload={'sha256': '0' * 64})
        self.assertEqual(a.event_id, b.event_id)

    def test_replay_rebuilds_candidate_before_decision(self):
        broker, router, intake = chain()
        decision = router.decide(intake[0].event_id, release())
        ids = [e.event_id for e in broker.replay('#')]
        self.assertLess(ids.index(intake[0].event_id), ids.index(decision.event_id))


V2 = 'agent.interaction' in KINDS


@unittest.skipUnless(V2, 'datamesh-event/v2 (agent.interaction, recorded_at, principal_id) not implemented')
class EventChainV2(unittest.TestCase):
    """Part B: proposed datamesh-event/v2. Fill in once the envelope exists."""

    def test_agent_interaction_is_information_exchange(self):
        """agent.interaction never carries a decision and is never a commitment kind."""
        self.assertNotIn('agent.interaction', COMMITMENT_KINDS)

    def test_agent_interaction_names_a_principal(self):
        """Every agent.interaction carries principal_id; the agent is never its own principal."""
        self.fail('write when the v2 envelope lands')

    def test_agent_interaction_references_snapshot_by_digest(self):
        """Payload holds a snapshot store key and SHA-256 only; raw payloads stay in infrastructure."""
        self.fail('write when the v2 envelope lands')

    def test_two_clocks(self):
        """recorded_at is set by the broker, never before occurred_at; corrections append, never overwrite."""
        self.fail('write when the v2 envelope lands')

    def test_agent_interaction_cannot_cause_a_decision_alone(self):
        """A gate.decision may cite agent.interaction events as evidence, but its cause is a candidate and
        its authority is a Person's; an automated counterparty 'accepted' reply is evidence, not commitment."""
        self.fail('write when the v2 envelope lands')

    def test_v1_reads_v2_writes(self):
        """Legacy v1 envelopes read; new envelopes written as v2; ambiguous mixes rejected; digests change."""
        self.fail('write when the v2 envelope lands')


if __name__ == '__main__':
    unittest.main()
