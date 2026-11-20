"""P4 domain invariants; not persistence, external authority resolution or orchestration."""
import ast
import importlib
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
import unittest
from uuid import uuid4
from pydantic import ValidationError
from app.domain.shared.versioning import VersionRef
from app.domain.workflow.lifecycle_state import LifecycleState
from app.domain.workflow.transition_definition import TransitionDefinition
from app.domain.workflow.workflow_definition import WorkflowDefinition
from app.domain.workflow.workflow_instance import WorkflowInstance
from app.domain.workflow.state_transition import StateTransition
from app.domain.quality.gate_criterion_definition import GateCriterionDefinition
from app.domain.quality.gate_approval_requirement import GateApprovalRequirement
from app.domain.quality.quality_gate_definition import QualityGateDefinition
from app.domain.quality.gate_criterion_result import GateCriterionResult
from app.domain.quality.quality_gate_instance import QualityGateInstance
from app.domain.quality.approval import Approval
from app.domain.quality.gate_decision import GateDecision
from app.domain.quality.nonconformity import Nonconformity
from app.domain.quality.corrective_action import CorrectiveAction
from app.domain.quality.verification_activity import VerificationActivity
from app.domain.project.milestone import Milestone
from app.domain.quality.milestone_sign_off import MilestoneSignOff

MODELS = (LifecycleState, TransitionDefinition, WorkflowDefinition, WorkflowInstance,
          StateTransition, GateCriterionDefinition, GateApprovalRequirement,
          QualityGateDefinition, GateCriterionResult, QualityGateInstance,
          Approval, GateDecision, Nonconformity, CorrectiveAction,
          VerificationActivity, Milestone, MilestoneSignOff)
AT = datetime(2026, 11, 20, 4, tzinfo=timezone.utc)


def ref():
    return VersionRef(identity=uuid4(), version=1)


def revise(record, **changes):
    return type(record).model_validate({**record.model_dump(), **changes})


def build_context(control='human_gate'):
    one = LifecycleState(entity_id=uuid4(), code='requested', display_name='Requested', initial=True)
    two = LifecycleState(entity_id=uuid4(), code='published', display_name='Published', terminal=True)
    criterion = GateCriterionDefinition(entity_id=uuid4(), code='integrity', requirement='mandatory',
                                        predicate_version='integrity:v1', description='Reconciled inputs')
    requirement = GateApprovalRequirement(entity_id=uuid4(), scope='release', purpose='publish', holder_role='reviewer')
    gate = QualityGateDefinition(entity_id=uuid4(), code='review', criteria=(criterion,),
                                 approval_requirements=(requirement,))
    edge = TransitionDefinition(entity_id=uuid4(), code='finish', from_state=one.ref(), to_state=two.ref(),
        purpose='publish', control=control, gate=gate.ref() if control == 'human_gate' else None,
        policy_version='synthetic:v1' if control == 'automatic_policy' else None)
    definition = WorkflowDefinition(entity_id=uuid4(), code='test', states=(one, two), transitions=(edge,))
    target = ref()
    instance = WorkflowInstance(entity_id=uuid4(), definition=definition.ref(), target=target,
                                 current_state=one.ref(), started_at=AT)
    result = GateCriterionResult(entity_id=uuid4(), definition=criterion.ref(), target=target,
        applicability='yes', evidence_condition='sufficient', result='pass', evidence=(ref(),), evaluated_at=AT)
    evaluation = QualityGateInstance(entity_id=uuid4(), definition=gate.ref(), target=target,
                                      results=(result,), evaluated_at=AT)
    approval = Approval(entity_id=uuid4(), requirement=requirement.ref(), target=target,
        evaluation=evaluation.ref(), actor_id=uuid4(), holder_role='reviewer', scope='release',
        purpose='publish', authority_evidence=(ref(),), outcome='granted', recorded_at=AT)
    decision = GateDecision(entity_id=uuid4(), evaluation=evaluation.ref(), target=target,
        transition_definition=edge.ref(), execution_id='process:1', actor_id=uuid4(), scope='release',
        purpose='publish', authority_evidence=(ref(),), effect='release', approvals=(approval,), recorded_at=AT)
    return dict(one=one, two=two, criterion=criterion, requirement=requirement, gate=gate, edge=edge,
                definition=definition, target=target, instance=instance, result=result,
                evaluation=evaluation, approval=approval, decision=decision)


class P4DomainContracts(unittest.TestCase):
    def setUp(self):
        self.c = build_context()

    def test_all_17_concepts_require_identity_and_forbid_empty_scaffolds(self):
        self.assertEqual(len(MODELS), 17)
        for model in MODELS:
            with self.subTest(model=model.__name__):
                self.assertEqual(model.SCHEMA_STATUS, 'p4-proposal')
                with self.assertRaises(ValidationError):
                    model()
                self.assertFalse(model.model_json_schema()['additionalProperties'])
                self.assertTrue(model.model_config['frozen'])

    def test_valid_workflow_definition_is_roundtrippable_and_not_authority(self):
        for key in ('one', 'edge', 'definition', 'instance', 'criterion', 'requirement',
                    'gate', 'result', 'evaluation', 'approval', 'decision'):
            value = self.c[key]
            self.assertEqual(type(value).model_validate_json(value.model_dump_json()), value)
            with self.assertRaises(NotImplementedError):
                value.require_accepted_definition()
        self.c['instance'].validate_definition(self.c['definition'])
        self.c['decision'].validate_context(self.c['evaluation'], self.c['gate'], self.c['edge'])

    def test_workflow_rejects_wrong_state_versions_and_duplicate_edges(self):
        c = self.c
        for edges in ((c['edge'], c['edge']),
                      (revise(c['edge'], to_state=revise(c['two'].ref(), version=2)),)):
            with self.subTest(edges=edges), self.assertRaises(ValidationError):
                revise(c['definition'], transitions=edges)

    def test_workflow_initial_terminal_and_reachability_rules(self):
        c = self.c
        for states in ((revise(c['one'], initial=False), c['two']),
                       (c['one'], revise(c['two'], terminal=False)),
                       (c['one'], c['two'], LifecycleState(entity_id=uuid4(), code='orphan', display_name='Orphan'))):
            with self.subTest(states=states), self.assertRaises(ValidationError):
                revise(c['definition'], states=states)
        back = revise(c['edge'], entity_id=uuid4(), code='back', from_state=c['two'].ref(), to_state=c['one'].ref())
        with self.assertRaises(ValidationError):
            revise(c['definition'], transitions=(c['edge'], back))

    def test_transition_control_paths_are_mutually_exclusive(self):
        edge = self.c['edge']
        for update in ({'gate': None}, {'policy_version': 'p:v1'},
                       {'control': 'none'}, {'control': 'automatic_policy'},
                       {'to_state': edge.from_state}):
            with self.subTest(update=update), self.assertRaises(ValidationError):
                revise(edge, **update)
        automatic = build_context('automatic_policy')['edge']
        self.assertIsNone(automatic.gate)

    def test_conditional_definition_and_quorum_constraints(self):
        with self.assertRaises(ValidationError):
            revise(self.c['criterion'], requirement='conditional')
        with self.assertRaises(ValidationError):
            revise(self.c['requirement'], minimum_approvers=2, allowed_actors=(uuid4(),))
        with self.assertRaises(ValidationError):
            revise(self.c['requirement'], minimum_approvers=True)
        with self.assertRaises(ValidationError):
            revise(self.c['gate'], criteria=(self.c['criterion'], self.c['criterion']))

    def test_instance_definition_and_initial_state_versions(self):
        c = self.c
        for instance in (revise(c['instance'], definition=ref()),
                         revise(c['instance'], current_state=c['two'].ref())):
            with self.assertRaises(ValueError):
                instance.validate_definition(c['definition'])
        with self.assertRaises(ValidationError):
            revise(c['instance'], record_version=2)

    def test_truth_table_and_mandatory_inapplicability(self):
        c = self.c
        for condition, result in (('sufficient', 'pass'), ('fails', 'fail'), ('missing', 'missing'),
                                  ('conflicting', 'conflicting'), ('stale', 'stale')):
            row = revise(c['result'], evidence_condition=condition, result=result)
            self.assertEqual(row.blocks(c['criterion']), result != 'pass')
        row = revise(c['result'], applicability='no', result='not_applicable', applicability_reason='not in scope')
        with self.assertRaises(ValueError):
            row.blocks(c['criterion'])
        conditional = revise(c['criterion'], requirement='conditional', applicability_rule='rule:v1')
        self.assertFalse(revise(row, definition=conditional.ref()).blocks(conditional))
        unknown = revise(c['result'], applicability='unknown', result='missing')
        self.assertTrue(unknown.blocks(c['criterion']))
        informational = revise(c['criterion'], requirement='informational')
        self.assertFalse(revise(unknown, definition=informational.ref()).blocks(informational))

    def test_result_evidence_and_definition_versions(self):
        c = self.c
        for update in ({'result': 'fail'}, {'evidence': ()}, {'evidence': (c['result'].evidence[0],)*2},
                       {'evaluated_at': AT.replace(tzinfo=None)}):
            with self.subTest(update=update), self.assertRaises(ValidationError):
                revise(c['result'], **update)
        with self.assertRaises(ValueError):
            c['result'].blocks(revise(c['criterion'], record_version=2))

    def test_evaluation_complete_definition_and_target_coverage(self):
        c = self.c
        self.assertTrue(c['evaluation'].passes(c['gate']))
        with self.assertRaises(ValidationError):
            revise(c['evaluation'], results=(revise(c['result'], target=ref()),))
        with self.assertRaises(ValidationError):
            revise(c['evaluation'], results=(c['result'], c['result']))
        changed_result = revise(c['result'], definition=ref())
        with self.assertRaises(ValueError):
            revise(c['evaluation'], results=(changed_result,)).passes(c['gate'])

    def test_passing_evaluation_is_not_human_approval(self):
        c = self.c
        with self.assertRaisesRegex(ValueError, 'quorum'):
            revise(c['decision'], approvals=()).validate_context(c['evaluation'], c['gate'], c['edge'])

    def test_approval_exact_target_evaluation_scope_purpose_role_and_version(self):
        c = self.c
        for update in ({'target': ref()}, {'evaluation': ref()}, {'scope': 'spend'},
                       {'purpose': 'other'}, {'holder_role': 'other'}, {'requirement': ref()},
                       {'outcome': 'revoked'}, {'outcome': 'rejected'}):
            with self.subTest(update=update), self.assertRaises(ValueError):
                revise(c['approval'], **update).validate_requirement(c['requirement'],
                    target=c['target'], evaluation=c['evaluation'].ref(), at=AT)

    def test_approval_expiry_future_response_and_independence(self):
        c = self.c
        approval = revise(c['approval'], expires_at=AT+timedelta(hours=1))
        for at in (AT-timedelta(seconds=1), AT+timedelta(hours=1)):
            with self.assertRaises(ValueError):
                approval.validate_requirement(c['requirement'], target=c['target'], evaluation=c['evaluation'].ref(), at=at)
        requirement = revise(c['requirement'], independent_from_executor=True)
        with self.assertRaisesRegex(ValueError, 'independent'):
            c['approval'].validate_requirement(requirement, target=c['target'], evaluation=c['evaluation'].ref(),
                                               at=AT, executor_id=c['approval'].actor_id)
        with self.assertRaises(ValueError):
            c['approval'].validate_requirement(revise(c['requirement'], allowed_actors=(uuid4(),)),
                target=c['target'], evaluation=c['evaluation'].ref(), at=AT)

    def test_duplicate_actor_cannot_satisfy_two_person_quorum(self):
        c = self.c
        requirement = revise(c['requirement'], minimum_approvers=2)
        gate = revise(c['gate'], approval_requirements=(requirement,))
        second = revise(c['approval'], entity_id=uuid4())
        with self.assertRaisesRegex(ValueError, 'quorum'):
            revise(c['decision'], approvals=(c['approval'], second)).validate_context(c['evaluation'], gate, c['edge'])

    def test_blocking_evaluation_cannot_release_but_can_hold(self):
        c = self.c
        bad_result = revise(c['result'], evidence_condition='missing', result='missing', evidence=())
        bad_eval = revise(c['evaluation'], results=(bad_result,))
        with self.assertRaisesRegex(ValueError, 'blocking'):
            c['decision'].validate_context(bad_eval, c['gate'], c['edge'])
        revise(c['decision'], effect='hold', scope='hold', approvals=()).validate_context(bad_eval, c['gate'], c['edge'])

    def make_transition(self, c=None, **changes):
        c = c or self.c
        args = dict(entity_id=uuid4(), workflow=c['instance'].ref(), definition=c['edge'].ref(),
                    target=c['target'], from_state=c['one'].ref(), to_state=c['two'].ref(),
                    execution_id='process:1', committed_workflow_version=2, occurred_at=AT)
        args.update(changes)
        return StateTransition(**args)

    def test_human_transition_exact_decision_execution_and_version(self):
        c = self.c
        step = self.make_transition(gate_decision=c['decision'].ref())
        step.validate_context(c['instance'], c['definition'], c['decision'])
        for decision in (None, revise(c['decision'], execution_id='other'),
                         revise(c['decision'], record_version=2),
                         revise(c['decision'], effect='hold', scope='hold')):
            with self.subTest(decision=decision), self.assertRaises(ValueError):
                step.validate_context(c['instance'], c['definition'], decision)
        with self.assertRaises(ValidationError):
            revise(step, committed_workflow_version=3)

    def test_automatic_publication_link_cannot_be_replaced_by_human_decision(self):
        c = build_context('automatic_policy')
        step = self.make_transition(c, policy_evaluation=ref(), policy_version='synthetic:v1')
        step.validate_context(c['instance'], c['definition'])
        with self.assertRaises(ValueError):
            step.validate_context(c['instance'], c['definition'], c['decision'])
        with self.assertRaises(ValidationError):
            revise(step, gate_decision=c['decision'].ref())
        with self.assertRaises(ValueError):
            revise(step, policy_version='other').validate_context(c['instance'], c['definition'])
        with self.assertRaises(ValueError):
            self.make_transition(c).validate_context(c['instance'], c['definition'])

    def test_retry_attempt_and_exact_workflow_context(self):
        c = self.c
        edge = revise(c['edge'], requires_new_attempt=True)
        definition = revise(c['definition'], transitions=(edge,))
        step = self.make_transition(gate_decision=c['decision'].ref())
        with self.assertRaisesRegex(ValueError, 'attempt'):
            step.validate_context(c['instance'], definition, c['decision'])
        revise(step, attempt=ref()).validate_context(c['instance'], definition, c['decision'])
        for update in ({'target': ref()}, {'definition': ref()}, {'workflow': ref()},
                       {'occurred_at': AT-timedelta(seconds=1)}):
            with self.subTest(update=update), self.assertRaises(ValueError):
                revise(step, **update).validate_context(c['instance'], definition, c['decision'])

    def test_nonconformity_lifecycle_preserves_versions_and_reopening(self):
        finding = Nonconformity(entity_id=uuid4(), target=ref(), description='suspected mismatch',
                                status='suspected', recorded_at=AT)
        confirmed = revise(finding, record_version=2, previous=finding.ref(), status='confirmed', evidence=(ref(),))
        confirmed.validate_previous(finding)
        closed = revise(confirmed, record_version=3, previous=confirmed.ref(), status='closed', closure_evidence=(ref(),))
        closed.validate_previous(confirmed)
        reopened = revise(closed, record_version=4, previous=closed.ref(), status='reopened', closure_evidence=(), reopening_reason='new evidence')
        reopened.validate_previous(closed)
        with self.assertRaises(ValidationError):
            revise(reopened, reopening_reason=None)
        with self.assertRaises(ValidationError):
            revise(confirmed, previous=ref())
        with self.assertRaises(ValidationError):
            revise(confirmed, evidence=())
        with self.assertRaises(ValueError):
            revise(closed, status='confirmed', closure_evidence=()).validate_previous(closed)

    def make_correction(self, independent=False):
        actor = uuid4()
        identity = uuid4()
        action = CorrectiveAction(entity_id=identity, nonconformity=ref(), target=ref(), description='repair',
            status='implemented', implemented_by=actor, implemented_at=AT,
            implemented_version=VersionRef(identity=identity, version=1), implementation_evidence=(ref(),),
            independent_verification_required=independent)
        verification = VerificationActivity(entity_id=uuid4(), action=action.ref(), target=action.target,
            verifier_id=actor, result='pass', evidence=(ref(),), verified_at=AT)
        closed = revise(action, record_version=2, status='closed', verifications=(verification.ref(),))
        return action, verification, closed

    def test_verification_independence_is_configurable_not_universal(self):
        action, verification, closed = self.make_correction()
        closed.validate_verifications((verification,), action)
        action, verification, closed = self.make_correction(True)
        with self.assertRaisesRegex(ValueError, 'independent'):
            closed.validate_verifications((verification,), action)
        independent = revise(verification, verifier_id=uuid4())
        closed.validate_verifications((independent,), action)

    def test_verification_pins_implementation_target_and_evidence(self):
        action, verification, closed = self.make_correction()
        for update in ({'action': ref()}, {'target': ref()}, {'result': 'fail'},
                       {'verified_at': AT-timedelta(seconds=1)}):
            with self.subTest(update=update), self.assertRaises(ValueError):
                closed.validate_verifications((revise(verification, **update),), action)
        with self.assertRaises(ValidationError):
            revise(verification, evidence=())
        with self.assertRaises(ValueError):
            closed.validate_verifications((), action)
        with self.assertRaises(ValueError):
            closed.validate_verifications((verification,), revise(action, target=ref()))
        with self.assertRaises(ValidationError):
            revise(action, status='closed', verifications=())

    def test_planned_date_occurrence_and_signoff_are_separate(self):
        milestone = Milestone(entity_id=uuid4(), project_id=uuid4(), name='commissioned', planned_date=date(2026,11,20))
        self.assertIsNone(milestone.occurred_at)
        with self.assertRaises(ValidationError):
            revise(milestone, occurred_at=AT)
        occurred = revise(milestone, record_version=2, occurred_at=AT, occurrence_evidence=(ref(),))
        requirement = revise(self.c['requirement'], scope='milestone_sign_off', purpose='commissioning')
        approval = revise(self.c['approval'], requirement=requirement.ref(), target=occurred.ref(), evaluation=None,
                          scope='milestone_sign_off', purpose='commissioning')
        signoff = MilestoneSignOff(entity_id=uuid4(), milestone=occurred.ref(), approval=approval, signed_at=AT)
        signoff.validate_context(occurred, requirement)
        with self.assertRaises(ValueError):
            signoff.validate_context(revise(occurred, record_version=3), requirement)
        with self.assertRaises(ValueError):
            signoff.validate_context(revise(occurred, occurred_at=None, occurrence_evidence=()), requirement)
        with self.assertRaises(ValidationError):
            revise(signoff, approval=revise(approval, scope='release'))

    def test_layering_no_io_clocks_or_application_dependencies(self):
        for model in MODELS:
            path = Path(importlib.import_module(model.__module__).__file__)
            tree = ast.parse(path.read_text())
            imports = {n.module for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)}
            self.assertFalse({m for m in imports if m and m.startswith(('app.application', 'app.infrastructure', 'app.interfaces'))})
            for node in ast.walk(tree):
                if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                    self.assertNotIn(node.func.attr, {'now', 'today', 'utcnow'})


if __name__ == '__main__':
    unittest.main()
