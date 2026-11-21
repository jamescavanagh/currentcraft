"""Acceptance for the synthetic framework-profile example.

See docs/domain/FRAMEWORK_PROFILES.md. Real framework profiles are private and never live in the
public tree; these tests only check the synthetic fixture against the documented rules.
"""
import json, unittest
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MANIFEST = json.loads((ROOT / 'docs/domain/domain_scaffold_manifest.json').read_text())['entries']
PROFILES = json.loads((ROOT / 'tests/fixtures/framework_profiles/synthetic_profiles.json').read_text())['profiles']
ROLES = {'primary', 'secondary', 'gap'}
COVERAGE = {'native', 'mapped', 'mapped, partial', 'mapped, gap filled'}
KEYS = {'schema', 'framework_id', 'framework_edition', 'kind', 'profile_version', 'source_digest',
        'valid_from', 'valid_to', 'concepts'}


def concepts(kind=None):
    for p in PROFILES:
        if kind is None or p['kind'] == kind:
            for c in p['concepts']:
                yield p, c


class SyntheticFrameworkProfiles(unittest.TestCase):
    def test_profiles_are_closed_and_synthetic(self):
        for p in PROFILES:
            self.assertEqual(set(p), KEYS, p['framework_id'])
            self.assertEqual(p['schema'], 'framework-profile/0')
            self.assertTrue(p['framework_id'].startswith('SYN-'), 'public fixtures are synthetic only')
            self.assertIn(p['kind'], {'primary', 'gap'})
            self.assertRegex(p['source_digest'], r'^[0-9a-f]{64}$')

    def test_maps_to_is_null_or_a_domain_class(self):
        names = {e['class_name'] for e in MANIFEST}
        for p, c in concepts():
            if c['maps_to'] is not None:
                self.assertIn(c['maps_to'], names, c['concept_id'])

    def test_roles_and_coverage_labels(self):
        for p, c in concepts():
            self.assertIn(c['role'], ROLES, c['concept_id'])
            self.assertIn(c['coverage'], COVERAGE, c['concept_id'])

    def test_one_primary_framework_per_domain(self):
        primary = {}
        for p, c in concepts('primary'):
            if c['role'] == 'primary':
                primary.setdefault(c['domain'], set()).add(p['framework_id'])
        for domain, frameworks in primary.items():
            self.assertEqual(len(frameworks), 1, domain)

    def test_gap_concepts_only_in_gap_profiles(self):
        for p, c in concepts():
            is_gap = c['role'] == 'gap'
            self.assertEqual(is_gap, p['kind'] == 'gap', c['concept_id'])
            if is_gap:
                self.assertEqual(c['coverage'], 'mapped, gap filled')
                self.assertTrue(c.get('gap'))

    def test_partial_primary_names_its_gap(self):
        for p, c in concepts('primary'):
            if c['coverage'] == 'mapped, partial':
                self.assertTrue(c.get('gap'), c['concept_id'])

    def test_validity_windows_are_timezone_aware(self):
        for p in PROFILES:
            for key in ('valid_from', 'valid_to'):
                if p[key] is not None:
                    self.assertIsNotNone(datetime.fromisoformat(p[key]).tzinfo, key)


if __name__ == '__main__':
    unittest.main()
