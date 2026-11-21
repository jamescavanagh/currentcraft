"""Acceptance for the synthetic meta-framework test envelope.

Fixture: tests/fixtures/framework_profiles/framework.meta.synthetic.v1.json. A fictional standard
used to generate tests and synthetic data. It confers no approval, compatibility or conformance,
and real framework content stays private. See docs/domain/FRAMEWORK_PROFILES.md.
"""
import hashlib, importlib, json, sys, unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / 'src'))
ENVELOPE = json.loads((ROOT / 'tests/fixtures/framework_profiles/framework.meta.synthetic.v1.json').read_text())
META = ENVELOPE['meta_content']
CLASSES = {
    'ReferenceSet': 'app.domain.reference.reference_set',
    'ReferenceValue': 'app.domain.reference.reference_value',
    'StandardsOrganization': 'app.domain.standards.standards_organization',
    'Standard': 'app.domain.standards.standard',
    'StandardEdition': 'app.domain.standards.standard_edition',
    'StandardClause': 'app.domain.standards.standard_clause',
    'SpecificationReference': 'app.domain.standards.specification_reference',
}
VERBAL_FORM = {
    'requirement': 'shall', 'prohibition': 'shall not', 'recommendation': 'should',
    'permission': 'may', 'possibility': 'can', 'capability': 'can', 'statement': None,
}
TESTABLE = {'requirement', 'prohibition'}


def domain_class(name):
    return getattr(importlib.import_module(CLASSES[name]), name)


def alphabet(reference_id):
    ref = next(r for r in META['normative_references'] if r['reference_id'] == reference_id)
    return set(ref['definition']['symbols'])


def marker_present(record, clause):
    return bool(record.get('marker'))


def marker_allowed(record, clause):
    allowed = set().union(*(alphabet(r) for r in clause['reference_ids']))
    return record.get('marker') in allowed


PREDICATES = {'marker_present': marker_present, 'marker_allowed': marker_allowed}


class SyntheticMetaFramework(unittest.TestCase):
    def test_envelope_is_synthetic_and_confers_no_authority(self):
        self.assertIs(ENVELOPE['synthetic'], True)
        self.assertTrue(ENVELOPE['authority'].startswith('none'))
        self.assertIn('private mappings', ENVELOPE['not_included'])
        self.assertEqual(META['identity']['publication_status'], 'synthetic_test_only')

    def test_meta_content_digest(self):
        canonical = json.dumps(META, sort_keys=True, separators=(',', ':'), ensure_ascii=False)
        self.assertEqual(hashlib.sha256(canonical.encode('utf-8')).hexdigest(), ENVELOPE['meta_content_sha256'])

    def test_records_validate_against_domain_classes(self):
        ids = {}
        for record in ENVELOPE['records']:
            obj = domain_class(record['object_type']).model_validate(record['payload'])
            ids[record['test_label']] = obj
        reference_set = ids['framework-vocabulary']
        for label in ('fictional-concept-one', 'fictional-concept-two'):
            self.assertEqual(ids[label].reference_set_id, reference_set.entity_id)

    def test_scaffolds_reject_fields_they_cannot_capture(self):
        for rejection in ENVELOPE['expected_scaffold_rejections']:
            cls = domain_class(rejection['object_type'])
            with self.assertRaises(ValueError, msg=rejection['object_type']):
                cls.model_validate({rejection['field']: rejection['value']})

    def test_verbal_form_matches_provision_kind(self):
        for clause in META['clauses']:
            self.assertEqual(clause['verbal_form'], VERBAL_FORM[clause['provision_kind']], clause['id'])
            if clause['element_kind'] == 'informative':
                self.assertIsNone(clause['verbal_form'], clause['id'])

    def test_only_requirements_and_prohibitions_are_testable(self):
        for clause in META['clauses']:
            if clause['provision_kind'] in TESTABLE:
                self.assertIn(clause['test_predicate'], PREDICATES, clause['id'])
            else:
                self.assertIsNone(clause['test_predicate'], clause['id'])

    def test_normative_references_are_dated_and_resolved(self):
        normative = {r['reference_id']: r for r in META['normative_references']}
        for ref in normative.values():
            self.assertEqual(ref['binding'], 'dated')
            self.assertEqual(ref['status'], 'resolved')
        for clause in META['clauses']:
            for ref_id in clause['reference_ids']:
                self.assertIn(ref_id, normative, clause['id'])
        for ref in META['informative_references']:
            if ref['status'] == 'unresolved':
                self.assertTrue(ref.get('reason'))

    def test_generated_records_against_testable_clauses(self):
        cases = [({'marker': 'ALPHA'}, True), ({'marker': 'BETA'}, True),
                 ({}, False), ({'marker': 'GAMMA'}, False)]
        clauses = [c for c in META['clauses'] if c['test_predicate']]
        for record, expected in cases:
            passed = all(PREDICATES[c['test_predicate']](record, c) for c in clauses)
            self.assertEqual(passed, expected, record)

    def test_informative_material_never_executes(self):
        for annex in META['annexes']:
            self.assertEqual(annex['element_kind'], 'informative')
        for note in META['notes']:
            self.assertNotIn('test_predicate', note)


if __name__ == '__main__':
    unittest.main()
