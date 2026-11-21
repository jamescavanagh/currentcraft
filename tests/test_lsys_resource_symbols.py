"""Acceptance: resources are never L-system grammar symbols.

Objects are things, never people. Employee, Contributor and Agent are resources; they may appear
only through a CapabilityBinding on a ProcessExecution, never as an axiom, nonterminal, terminal
or verb argument. See docs/domain/LSYS_DOMAIN_VOCABULARY.md.
"""
import importlib, json, re, sys, unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / 'src'))
MANIFEST = json.loads((ROOT / 'docs/domain/domain_scaffold_manifest.json').read_text())['entries']
CASES = json.loads((ROOT / 'tests/fixtures/lsys/resource_symbol_cases.json').read_text())
DOC = (ROOT / 'docs/domain/LSYS_DOMAIN_VOCABULARY.md').read_text()
ALPHABET_SECTIONS = ('Symbol kinds', 'Relations the grammar may expect', 'Candidate productions, read as domain objects')
EXPECTED_RESOURCES = {'Employee', 'Contributor', 'Agent'}


def resource_classes():
    """Discover resources from the domain, never from a hand-kept list."""
    from app.domain.workforce.resource import Resource
    found = {'Resource'}
    for e in MANIFEST:
        cls = getattr(importlib.import_module(e['module']), e['class_name'])
        if isinstance(cls, type) and issubclass(cls, Resource):
            found.add(e['class_name'])
    return found


def profile_symbols(profile):
    """Every symbol a profile names, in the proposed profile shape."""
    yield profile.get('axiom', '')
    for p in profile.get('productions', ()):
        yield p['predecessor']
        yield from p['successor']
    for x in profile.get('expectations', ()):
        yield from x['args']


def offending(profile, resources):
    """Reference oracle: symbols that name a resource after trimming and case folding."""
    folded = {r.casefold() for r in resources}
    return [s for s in profile_symbols(profile) if s.strip().casefold() in folded]


def alphabet_table_tokens(doc):
    """Identifier tokens inside code spans of the alphabet tables only (prose may name resources)."""
    tokens, section = set(), None
    for line in doc.splitlines():
        heading = re.match(r'#{2,3} (.+)', line)
        if heading:
            section = heading.group(1).strip()
        elif section in ALPHABET_SECTIONS and line.startswith('|'):
            for span in re.findall(r'`([^`]+)`', line):
                tokens |= set(re.findall(r'[A-Za-z_][A-Za-z0-9_]*', span))
    return tokens


class ResourceSymbolAcceptance(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.resources = resource_classes()

    def test_resource_population_is_reviewed(self):
        # A new Resource subclass must be reviewed here before the grammar can be trusted to exclude it.
        self.assertEqual(self.resources - {'Resource'}, EXPECTED_RESOURCES)

    def test_loader_resource_set_matches_domain_discovery(self):
        from app.application.lsys import RESOURCES
        self.assertEqual(set(RESOURCES), self.resources)

    def test_vocabulary_alphabet_names_no_resource(self):
        tokens = alphabet_table_tokens(DOC)
        self.assertIn('Project', tokens)  # the parser actually read the tables
        self.assertFalse(tokens & self.resources, sorted(tokens & self.resources))

    def test_vocabulary_marks_resources_out_of_alphabet(self):
        row = next(l for l in DOC.splitlines() if l.startswith('| Employees and Contributors'))
        self.assertIn('not in the alphabet', row)

    def test_every_reject_case_is_caught_by_the_oracle(self):
        for c in CASES['reject']:
            with self.subTest(case=c['case']):
                self.assertEqual(offending(c['profile'], self.resources), [c['offender']])

    def test_every_accept_case_is_clean_and_names_real_objects(self):
        names = {e['class_name'] for e in MANIFEST} | {'o'}
        for c in CASES['accept']:
            with self.subTest(case=c['case']):
                syms = list(profile_symbols(c['profile']))
                self.assertEqual(offending(c['profile'], self.resources), [])
                self.assertTrue(set(syms) <= names, sorted(set(syms) - names))

    def test_fixture_covers_every_resource_and_every_position(self):
        offenders = {c['offender'].strip().casefold() for c in CASES['reject']}
        self.assertTrue({r.casefold() for r in self.resources} <= offenders)
        self.assertTrue({'resource_as_axiom', 'resource_as_predecessor', 'resource_as_terminal_in_successor',
                         'resource_in_verb_argument'} <= {c['case'] for c in CASES['reject']})

    def test_process_first_rejects_a_resource_used_as_an_object(self):
        from app.application.process import CapabilityBinding, ObjectIncidence, ProcessExecution, ProcessType
        design = ProcessType(code='design', name='Design package', function_classes=('transform',))
        with self.assertRaises(ValueError):
            ProcessExecution(execution_id='demo:design:1', process=design, stage='S2',
                incidence=(ObjectIncidence(object_id='res-designer', effect='produces', state_after='draft'),),
                executed_by=(CapabilityBinding(resource_id='res-designer', resource_role='designer'),))

    def test_grammar_loader_rejects_resource_symbols(self):
        # Formerly skipped until the loader existed; it now always runs and CI forbids skips here.
        from app.application.lsys import load_profile
        for c in CASES['reject']:
            with self.subTest(case=c['case']), self.assertRaisesRegex(ValueError, 'resource symbol rejected'):
                load_profile(c['profile'])
        for c in CASES['accept']:
            with self.subTest(case=c['case']):
                load_profile(c['profile'])


if __name__ == '__main__':
    unittest.main()
