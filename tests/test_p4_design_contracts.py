"""First-change negative and fixture tests; no P4 runtime is asserted here."""
import json
import sys
import unittest
from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path
from uuid import uuid4

from pydantic import ValidationError

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
from app.application.p4.contracts import (AppliedTransition, Association, CommittedExecutionRef,
    CommittedGateDecisionRef, CommittedPolicyEvaluationRef, CriterionAssessment,
    DeliveryAcknowledgment, ExtractionManifest, GenerationRequest, MeasureDefinition, MeasureInput, PublicSourceRecord,
    ReportCalendar, WorkflowIIdentity, VersionRef, aggregate_measure, replay_transitions, resume_action)

FIXTURE = json.loads((ROOT / 'tests/fixtures/p4/workflow_i.synthetic.json').read_text())


def changed(model, **changes):
    return type(model).model_validate({**model.model_dump(), **changes})


class P4DesignContracts(unittest.TestCase):
    def test_fixture_and_calendar_fallback(self):
        calendar = ReportCalendar.model_validate(FIXTURE['calendar'])
        self.assertEqual(calendar.assigned_source_time(date(2026, 11, 18)).isoformat(), '2026-11-18T09:00:00-08:00')
        self.assertEqual(calendar.assigned_source_time(date(2026, 7, 18)).isoformat(), '2026-07-18T09:00:00-07:00')
        self.assertEqual(GenerationRequest.model_validate(FIXTURE['request']).schema_version, 'workflow-i-request/v1')
        self.assertTrue(ExtractionManifest.model_validate(FIXTURE['source_manifest']).complete)
        calendar.check_request(GenerationRequest.model_validate(FIXTURE['request']))
        with self.assertRaisesRegex(ValueError, 'cutoff'):
            calendar.check_request(changed(GenerationRequest.model_validate(FIXTURE['request']),
                                           cutoff_exclusive=datetime.fromisoformat('2026-11-19T07:00:00-08:00')))
        self.assertEqual(PublicSourceRecord.model_validate(FIXTURE['public_source_record']).date_precision, 'source_date_assigned')
        self.assertFalse(Association.model_validate(FIXTURE['unresolved_candidate']).confirmed)

    def test_request_key_fingerprint_and_time_canonicalization(self):
        original = GenerationRequest.model_validate(FIXTURE['request'])
        equivalent = changed(original, window_start=original.window_start.astimezone(timezone.utc),
                             cutoff_exclusive=original.cutoff_exclusive.astimezone(timezone.utc))
        self.assertEqual(original.fingerprint(), equivalent.fingerprint())
        self.assertTrue(original.matches_retry(equivalent))
        for update in ({'calendar_version': 2}, {'policy_version': 'new-policy'},
                       {'cutoff_exclusive': datetime.fromisoformat('2026-11-19T07:00:00-08:00')},
                       {'mode': 'refresh'}):
            with self.subTest(update=update), self.assertRaises(ValueError):
                original.matches_retry(changed(original, **update))
        with self.assertRaises(ValidationError):
            changed(original, mode='reproduce')
        with self.assertRaises(ValidationError):
            changed(original, window_start=datetime(2026, 11, 18))

    def test_separate_identity_and_version(self):
        ids = [uuid4() for _ in range(6)]
        identity = WorkflowIIdentity(project_id=ids[0], logical_product_id=ids[1], run_id=ids[2],
                                     product=VersionRef(identity=ids[3], version=1),
                                     evaluation=VersionRef(identity=ids[4], version=1),
                                     graph=VersionRef(identity=ids[5], version=1))
        with self.assertRaises(ValidationError):
            changed(identity, run_id=ids[0])
        with self.assertRaises(ValidationError):
            VersionRef(identity=uuid4(), version=0)

    def test_resume_requires_exact_pinned_snapshot(self):
        saved = ExtractionManifest.model_validate(FIXTURE['source_manifest'])
        self.assertEqual(resume_action(saved, saved), 'reuse')
        self.assertEqual(resume_action(saved, changed(saved, snapshot_token='new')), 'refetch')
        self.assertEqual(resume_action(saved, changed(saved, content_digest='b'*64)), 'block')
        self.assertEqual(resume_action(saved, changed(saved, complete=False)), 'block')
        self.assertEqual(resume_action(saved, changed(saved, source_profile='other')), 'block')
        best_effort = changed(saved, capability='best_effort', snapshot_token=None, limitation='no cross-page snapshot')
        self.assertEqual(resume_action(best_effort, best_effort), 'reuse')
        self.assertEqual(resume_action(best_effort, changed(best_effort, extraction_id=uuid4())), 'block')
        with self.assertRaises(ValidationError):
            changed(saved, snapshot_token=None)

    def test_associations_do_not_confirm_candidates(self):
        candidate = Association.model_validate(FIXTURE['unresolved_candidate'])
        with self.assertRaises(ValidationError):
            changed(candidate, basis='reviewed_mapping')
        with self.assertRaises(ValidationError):
            changed(candidate, basis='hil_confirmed')
        confirmed = changed(candidate, basis='hil_confirmed', label_event_id=uuid4())
        self.assertTrue(confirmed.confirmed)
        self.assertFalse(changed(confirmed, conflicting_evidence_ids=(uuid4(),)).confirmed)

    def test_gates_separate_requirement_applicability_and_evidence(self):
        for evidence, result in [('sufficient','pass'), ('fails','fail'), ('missing','missing'),
                                 ('conflicting','conflicting'), ('stale','stale')]:
            row = CriterionAssessment(requirement='conditional', applicability='yes',
                                      evidence=evidence, result=result)
            self.assertEqual(row.blocks_transition, result != 'pass')
        unknown = CriterionAssessment(requirement='conditional', applicability='unknown', evidence='sufficient', result='missing')
        self.assertTrue(unknown.blocks_transition)
        self.assertFalse(CriterionAssessment(requirement='informational', applicability='unknown', evidence='missing', result='missing').blocks_transition)
        self.assertFalse(CriterionAssessment(requirement='conditional', applicability='no', evidence='missing', result='not_applicable').blocks_transition)
        for invalid in ({'requirement':'mandatory', 'applicability':'no', 'evidence':'missing','result':'not_applicable'},
                        {'requirement':'conditional','applicability':'unknown','evidence':'sufficient','result':'not_applicable'}):
            with self.assertRaises(ValidationError):
                CriterionAssessment(**invalid)

    def test_unconfirmed_records_cannot_enter_confirmed_totals(self):
        definition = MeasureDefinition(code='labor_recorded_hours', category='hourly_labor', grain='time_entry',
           unit='hour', inclusion_rule='confirmed project and evidenced hours',
           duplicate_rule='stable_source_id_and_version', unavailable_reason='unknown hours or project', definition_version='synthetic-v1')
        project, source, evidence = uuid4(), uuid4(), uuid4()
        item = MeasureInput(source_id=source, source_version='v1', measure_code='labor_recorded_hours', category='hourly_labor',
            amount=Decimal('8.25'), unit='hour', evidence_id=evidence, confirmed_project_id=project)
        self.assertEqual(aggregate_measure(definition, (item,item), project), Decimal('8.25'))
        self.assertIsNone(aggregate_measure(definition, (changed(item, confirmed_project_id=None),), project))
        with self.assertRaises(ValidationError):
            changed(item, unit='each')
        with self.assertRaisesRegex(ValueError, 'duplicate'):
            aggregate_measure(definition, (item, changed(item, source_version='v2')), project)
        with self.assertRaises(ValidationError):
            changed(item, amount=1.25)

    def test_measure_codes_reject_contradictory_grain_units_and_streams(self):
        fields = dict(category='product', grain='line', unit='source_currency', currency='USD',
                      inclusion_rule='evidenced project line', duplicate_rule='stable_source_id_and_version',
                      unavailable_reason='missing source', definition_version='synthetic-v1')
        sell = MeasureDefinition(code='so_sell', **fields)
        for wrong in ({'unit':'hour'}, {'grain':'time_entry'}, {'currency':None}, {'basis_code':'po_ordered'}):
            with self.subTest(wrong=wrong), self.assertRaises(ValidationError):
                changed(sell, **wrong)
        po = changed(sell, code='po_ordered')
        with self.assertRaises(ValidationError):
            changed(po, category='hourly_labor')
        category = changed(sell, code='category_total', grain='project_category', basis_code='so_sell')
        self.assertEqual(category.basis_code, 'so_sell')
        with self.assertRaises(ValidationError):
            changed(category, basis_code=None)
        with self.assertRaises(ValidationError):
            changed(category, unit='hour', currency=None)
        with self.assertRaises(ValidationError):
            changed(category, basis_code='po_ordered', category='hourly_labor')
        project = uuid4()
        input_sell = MeasureInput(source_id=uuid4(), source_version='1', measure_code='so_sell',
            category='product', amount=Decimal('10.00'), unit='source_currency', currency='USD',
            evidence_id=uuid4(), confirmed_project_id=project)
        self.assertEqual(aggregate_measure(category, (input_sell,), project), Decimal('10.00'))
        with self.assertRaisesRegex(ValueError, 'collision'):
            aggregate_measure(category, (input_sell, changed(input_sell, source_id=uuid4(), currency='EUR')), project)
        with self.assertRaisesRegex(ValueError, 'streams'):
            aggregate_measure(category, (input_sell, changed(input_sell, source_id=uuid4(), measure_code='po_ordered')), project)
        with self.assertRaises(ValidationError):
            changed(input_sell, measure_code='labor_recorded_hours')

    def test_history_replay_detects_corruption(self):
        run = uuid4()
        one = AppliedTransition(run_id=run, sequence=1, execution_id='process:1',
             from_state='Requested', to_state='In Process', expected_run_version=1, committed_run_version=2)
        two = AppliedTransition(run_id=run, sequence=2, execution_id='process:2',
             from_state='In Process', to_state='Prepared', expected_run_version=2, committed_run_version=3)
        target = VersionRef(identity=uuid4(), version=1)
        executions = {code: CommittedExecutionRef(execution_id=code, run_id=run, target=target)
                      for code in ('process:1', 'process:2')}
        self.assertEqual(replay_transitions(run, (one, two), executions), 'Prepared')
        for steps, refs in [((one,two), {'process:1': executions['process:1']}),
                            ((one,changed(two, sequence=3)), executions),
                            ((one,changed(two, from_state='Failure')), executions),
                            ((one,changed(two, to_state='Requested')), executions)]:
            with self.assertRaises(ValueError):
                replay_transitions(run, steps, refs)
        decision_id = uuid4()
        controlled = changed(two, gate_decision_id=decision_id)
        controlled_refs = {**executions, 'process:2': changed(executions['process:2'], gate_decision_id=decision_id)}
        with self.assertRaisesRegex(ValueError, 'gate decision'):
            replay_transitions(run, (one, controlled), controlled_refs)
        decision = CommittedGateDecisionRef(decision_id=decision_id, execution_id='process:2',
                                            run_id=run, evaluation=VersionRef(identity=uuid4(), version=1), target=target)
        self.assertEqual(replay_transitions(run, (one, controlled), controlled_refs, {decision_id: decision}), 'Prepared')
        with self.assertRaisesRegex(ValueError, 'gate decision'):
            replay_transitions(run, (one, controlled), controlled_refs,
                               {decision_id: changed(decision, target=VersionRef(identity=uuid4(), version=1))})

    def test_published_needs_verified_destination_ack(self):
        run = uuid4()
        base = dict(run_id=run, sequence=3, execution_id='process:3', from_state='Prepared',
                    to_state='Published', expected_run_version=3, committed_run_version=4)
        with self.assertRaisesRegex(ValidationError, 'publication'):
            AppliedTransition(**base)
        product = VersionRef(identity=uuid4(), version=1)
        ack = DeliveryAcknowledgment(attempt_id=uuid4(), product=product, destination_id=uuid4(),
                                     document_id='synthetic-document-1', acknowledged_at=datetime.fromisoformat('2026-11-19T14:15:00+00:00'))
        step = AppliedTransition(**base, delivery_ack=ack, policy_version='workflow-i-synthetic-publication/v1',
                                 policy_evaluation=VersionRef(identity=uuid4(), version=1))
        self.assertEqual(step.to_state, 'Published')
        with self.assertRaises(ValidationError):
            changed(ack, acknowledged_at=datetime(2026, 11, 19))

        first = AppliedTransition(run_id=run, sequence=1, execution_id='process:1',
            from_state='Requested', to_state='In Process', expected_run_version=1, committed_run_version=2)
        prepared = AppliedTransition(run_id=run, sequence=2, execution_id='process:2',
            from_state='In Process', to_state='Prepared', expected_run_version=2, committed_run_version=3)
        refs = {code: CommittedExecutionRef(execution_id=code, run_id=run, target=product)
                for code in ('process:1','process:2','process:3')}
        evidence = VersionRef(identity=uuid4(), version=1)
        evaluation = CommittedPolicyEvaluationRef(evaluation=step.policy_evaluation, run_id=run,
            target=product, policy_version=step.policy_version, outcome='permit', evidence=(evidence,))
        history = (first, prepared, step)
        self.assertEqual(replay_transitions(run, history, refs,
            committed_policy_evaluations={evaluation.evaluation:evaluation}), 'Published')
        for bad_evaluations in ({},
                                {evaluation.evaluation:changed(evaluation, outcome='block')},
                                {evaluation.evaluation:changed(evaluation, target=VersionRef(identity=uuid4(), version=1))},
                                {evaluation.evaluation:changed(evaluation, policy_version='another-policy')},
                                {evaluation.evaluation:changed(evaluation, run_id=uuid4())}):
            with self.subTest(bad=bad_evaluations), self.assertRaisesRegex(ValueError, 'evaluation'):
                replay_transitions(run, history, refs, committed_policy_evaluations=bad_evaluations)
        with self.assertRaisesRegex(ValueError, 'acknowledged product'):
            replay_transitions(run, (first, prepared, changed(step, delivery_ack=changed(ack,
                product=VersionRef(identity=uuid4(), version=1)))), refs,
                committed_policy_evaluations={evaluation.evaluation:evaluation})
        with self.assertRaisesRegex(ValidationError, 'automatic publication'):
            changed(step, gate_decision_id=uuid4())

    def test_public_ingress_rejects_sentinel_and_unknown_time(self):
        payload = dict(FIXTURE['public_source_record'])
        for leak in ('part_number','raw_source_ref','description'):
            with self.subTest(leak=leak), self.assertRaises(ValidationError):
                PublicSourceRecord.model_validate({**payload, leak:'PRIVATE_PART_SENTINEL_123'})
        with self.assertRaises(ValidationError):
            PublicSourceRecord.model_validate({**payload, 'date_precision':'unknown'})
        with self.assertRaises(ValidationError):
            PublicSourceRecord.model_validate({**payload, 'amount':12.5})
        for original_date, occurred_at in [
            ('2026-11-17','2026-11-18T09:00:00-08:00'),
            ('2026-11-18','2026-11-18T10:00:00-08:00'),
            ('2026-07-18','2026-07-18T09:00:00-08:00'),
            ('2026-11-18','2026-11-18T09:00:00-07:00'),
        ]:
            with self.subTest(original_date=original_date, occurred_at=occurred_at), self.assertRaises(ValidationError):
                PublicSourceRecord.model_validate({**payload, 'original_date':original_date, 'occurred_at':occurred_at})
        summer = PublicSourceRecord.model_validate({**payload, 'original_date':'2026-07-18',
            'occurred_at':'2026-07-18T09:00:00-07:00'})
        self.assertEqual(summer.date_precision, 'source_date_assigned')
        observed = PublicSourceRecord.model_validate({**payload, 'date_precision':'source_timestamp',
            'occurred_at':'2026-07-18T15:45:00+00:00', 'original_date':None})
        self.assertEqual(observed.occurred_at.isoformat(), '2026-07-18T15:45:00+00:00')
        schema = PublicSourceRecord.model_json_schema()
        self.assertFalse(schema['additionalProperties'])
        self.assertNotIn('part_number', str(schema))

    def test_release_allowlist_covers_only_p4_python_package(self):
        sys.path.insert(0, str(ROOT / 'scripts'))
        import check_release
        self.assertTrue(check_release.allowed('src/app/application/p4/contracts.py'))
        self.assertTrue(check_release.allowed('src/app/application/p4/__init__.py'))
        self.assertFalse(check_release.allowed('src/app/application/p4/private-mappings.json'))
        self.assertFalse(check_release.allowed('src/app/application/p4/part_numbers.txt'))


if __name__ == '__main__':
    unittest.main()
