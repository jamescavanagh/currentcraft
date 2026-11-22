"""L-system loader and growth acceptance (docs/domain/LSYS_DOMAIN_VOCABULARY.md).

Grammar proposes, evidence disposes, gates decide: every check here is synthetic and proves structure
only, never process validity or approval of a production.
"""
import copy, doctest, hashlib, json, sys, tempfile, unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / 'src'))

from pydantic import ValidationError  # noqa: E402

from app.application.ladder import apply_move, replay  # noqa: E402
from app.application.lsys import (  # noqa: E402
    LINKS, MAX_NODES, OBJECTS, RESOURCES, TERMINAL, VERBS, GrowthCount, grow, ladder_moves, load_profile, profile_digest,
)
from tests.test_simulation_layering import HEAVY, imports, py_files  # noqa: E402

FIX = json.loads((ROOT / 'tests/fixtures/lsys/synthetic_profiles.json').read_text())
PROJECT, NEED = FIX['project_profile'], FIX['need_profile']


def repin(profile):
    p = copy.deepcopy(profile)
    p['source_digest'] = profile_digest(p)
    return p


def count(pid, n, ev='ev-synthetic-1'):
    return GrowthCount(production_id=pid, count=n, evidence_ids=(ev,))


class Loader(unittest.TestCase):
    def test_synthetic_profiles_load(self):
        self.assertEqual(load_profile(PROJECT).axiom, 'Project')
        self.assertEqual(load_profile(NEED).axiom, 'Need')

    def test_profile_version_and_digest_are_required(self):
        for key in ('profile_version', 'source_digest'):
            bad = dict(PROJECT)
            del bad[key]
            with self.subTest(key=key), self.assertRaises(ValueError):
                load_profile(bad)

    def test_digest_must_match_content(self):
        bad = copy.deepcopy(PROJECT)
        bad['productions'][0]['successor'] = ['Subsystem']
        with self.assertRaisesRegex(ValueError, 'source_digest does not match'):
            load_profile(bad)
        self.assertEqual(load_profile(repin(bad)).productions[0].successor, ('Subsystem',))

    def test_digest_ignores_key_order_but_not_content(self):
        shuffled = {k: PROJECT[k] for k in reversed(list(PROJECT))}
        self.assertEqual(profile_digest(shuffled), PROJECT['source_digest'])
        self.assertEqual(PROJECT['source_digest'], hashlib.sha256(json.dumps({
            'axiom': PROJECT['axiom'], 'expectations': PROJECT['expectations'], 'productions': PROJECT['productions'],
            'profile_version': PROJECT['profile_version']}, sort_keys=True, separators=(',', ':')).encode()).hexdigest())

    def test_unknown_and_non_canonical_symbols_are_rejected(self):
        for sym in ('Widget', 'project', ' Project', 'Drawing', 'TimeCard', ''):
            bad = copy.deepcopy(PROJECT)
            bad['productions'][0]['successor'] = [sym]
            with self.subTest(sym=sym), self.assertRaises(ValueError):
                load_profile(repin(bad))

    def test_terminal_is_never_rewritten_or_axiom(self):
        for change in ({'axiom': TERMINAL}, {'productions': [{'id': 'p1', 'predecessor': TERMINAL, 'successor': ['Task']}]}):
            with self.subTest(change=change), self.assertRaises(ValueError):
                load_profile(repin(dict(PROJECT, **change)))

    def test_duplicate_production_ids_rejected(self):
        bad = dict(PROJECT, productions=PROJECT['productions'] + [PROJECT['productions'][0]])
        with self.assertRaisesRegex(ValueError, 'duplicate production id'):
            load_profile(repin(bad))

    def test_verbs_are_process_effects_plus_impedance_match(self):
        self.assertEqual(set(VERBS), {'produces', 'consumes', 'reads', 'revises', 'holds', 'transfers', 'checks', 'impedance_match'})
        for verb in ('hold', 'release', 'reject', 'return', 'approves'):
            with self.subTest(verb=verb), self.assertRaises(ValueError):
                load_profile(repin(dict(PROJECT, expectations=[{'verb': verb, 'args': ['Document']}])))

    def test_impedance_match_needs_exactly_two_objects(self):
        for args in (['Subsystem'], ['Subsystem', 'BOM', 'Document']):
            with self.subTest(args=args), self.assertRaisesRegex(ValueError, 'exactly two'):
                load_profile(repin(dict(PROJECT, expectations=[{'verb': 'impedance_match', 'args': args}])))

    def test_extra_fields_and_non_mappings_rejected(self):
        with self.assertRaises(ValueError):
            load_profile(repin(dict(PROJECT, approved_by='coordinator')))
        with self.assertRaises(ValueError):
            load_profile([PROJECT])

    def test_validation_error_is_a_value_error(self):
        self.assertTrue(issubclass(ValidationError, ValueError))


class Alphabet(unittest.TestCase):
    def test_alphabet_names_real_non_resource_domain_classes(self):
        for name, cls in OBJECTS.items():
            with self.subTest(name=name):
                self.assertEqual(cls.__name__, name)
                self.assertTrue(cls.__module__.startswith('app.domain.'))
                self.assertNotIn(name, RESOURCES)
                self.assertNotEqual(cls.SCHEMA_STATUS, 'unreviewed-scaffold')

    def test_every_link_is_an_existing_typed_field(self):
        for (parent, child), link in LINKS.items():
            holder, field = link.split('.')
            with self.subTest(link=link):
                self.assertIn(parent, OBJECTS)
                self.assertIn(child, OBJECTS)
                self.assertIn(holder, (parent, child))
                self.assertIn(field, OBJECTS[holder].model_fields)

    def test_candidate_production_link_status(self):
        links = {(l.production_id, l.successor): (l.status, l.link) for l in load_profile(PROJECT).links()}
        self.assertEqual(links, {
            ('p1', 'Location'): ('typed_link', 'Location.project_id'),
            ('p2', 'Subsystem'): ('typed_link', 'Subsystem.location_id'),
            ('p3', 'o'): ('terminal', None),
            ('p4', 'Document'): ('typed_link', 'Need.document_ids'),
            ('p5', 'BOM'): ('gap', None),
            ('p5', 'Scope'): ('typed_link', 'Scope.document_id'),
        })


class Growth(unittest.TestCase):
    def setUp(self):
        self.profile = load_profile(PROJECT)

    def test_no_count_no_growth(self):
        d = grow(self.profile)
        self.assertEqual([n.symbol for n in d.nodes], ['Project'])
        self.assertEqual([(u.production_id, u.reason) for u in d.unexpanded], [('p1', 'count_not_evidenced')])

    def test_counts_require_evidence(self):
        with self.assertRaises(ValidationError):
            GrowthCount(production_id='p1', count=2, evidence_ids=())
        with self.assertRaises(ValidationError):
            GrowthCount(production_id='p1', count=True, evidence_ids=('e',))

    def test_counts_must_name_known_unique_productions(self):
        with self.assertRaisesRegex(ValueError, 'unknown production'):
            grow(self.profile, (count('p9', 1),))
        with self.assertRaisesRegex(ValueError, 'duplicate count'):
            grow(self.profile, (count('p1', 1), count('p1', 2)))

    def test_bracketed_growth_shape(self):
        d = grow(self.profile, (count('p1', 2), count('p2', 3), count('p3', 4)))
        symbols = [n.symbol for n in d.nodes]
        self.assertEqual((symbols.count('Location'), symbols.count('Subsystem'), symbols.count(TERMINAL)), (2, 6, 24))
        by_id = {n.node_id: n for n in d.nodes}
        for n in d.nodes[1:]:
            self.assertEqual(by_id[n.parent_id].depth + 1, n.depth)
        self.assertEqual(d.unexpanded, ())

    def test_growth_is_deterministic_and_order_independent(self):
        a = grow(self.profile, (count('p1', 2), count('p2', 1)))
        b = grow(self.profile, (count('p2', 1), count('p1', 2)))
        self.assertEqual(a, b)
        self.assertNotEqual(a.derivation_id, grow(self.profile, (count('p1', 3), count('p2', 1))).derivation_id)
        self.assertNotEqual(a.derivation_id, grow(self.profile, (count('p1', 2, 'other'), count('p2', 1))).derivation_id)

    def test_every_node_is_possible_and_carries_the_digest(self):
        d = grow(self.profile, (count('p1', 2), count('p2', 2), count('p3', 2)))
        self.assertEqual({n.rung for n in d.nodes}, {'possible'})
        self.assertEqual(d.profile_digest, PROJECT['source_digest'])
        self.assertTrue(all(n.node_id.startswith(d.derivation_id + ':') for n in d.nodes))

    def test_depth_limit_is_recorded(self):
        d = grow(self.profile, (count('p1', 1), count('p2', 1), count('p3', 1)), max_depth=1)
        self.assertEqual([n.symbol for n in d.nodes], ['Project', 'Location'])
        self.assertEqual([(u.production_id, u.reason) for u in d.unexpanded], [('p2', 'depth_limit')])
        with self.assertRaises(ValueError):
            grow(self.profile, max_depth=-1)

    def test_node_bound(self):
        with self.assertRaisesRegex(ValueError, str(MAX_NODES)):
            grow(self.profile, (count('p1', 1000), count('p2', 1000)))

    def test_need_profile_reaches_bom_and_scope(self):
        d = grow(load_profile(NEED), (count('p4', 1), count('p5', 1)))
        self.assertEqual([(n.symbol, n.link_status) for n in d.nodes],
                         [('Need', None), ('Document', 'typed_link'), ('BOM', 'gap'), ('Scope', 'typed_link')])

    def test_expectations_are_carried_not_executed(self):
        d = grow(self.profile)
        self.assertEqual(d.expectations, self.profile.expectations)

    def test_growth_never_creates_domain_records(self):
        d = grow(self.profile, (count('p1', 2), count('p2', 2)))
        for n in d.nodes:
            self.assertFalse(type(n).__module__.startswith('app.domain'))


class LadderIntegration(unittest.TestCase):
    def test_growth_only_emits_grow_moves_that_land_at_possible(self):
        d = grow(load_profile(PROJECT), (count('p1', 3), count('p2', 2), count('p3', 2)))
        moves = ladder_moves(d)
        self.assertEqual(len(moves), len(d.nodes))
        for m in moves:
            self.assertEqual((m.verb, m.origin, m.derivation_id), ('grow', 'grammar_growth', d.derivation_id))
        self.assertEqual(replay(moves), {n.node_id: 'possible' for n in d.nodes})

    def test_growth_cannot_advance_a_grown_node(self):
        d = grow(load_profile(PROJECT), (count('p1', 1),))
        from app.application.ladder import LadderMove
        with self.assertRaises(ValueError):
            LadderMove(work_package_id=d.nodes[0].node_id, verb='release', origin='grammar_growth',
                       derivation_id=d.derivation_id)
        self.assertEqual(apply_move(None, ladder_moves(d)[0]), 'possible')


class FileAdapter(unittest.TestCase):
    def setUp(self):
        from app.infrastructure.lsys import read_profile
        self.read = read_profile
        self.dir = tempfile.TemporaryDirectory()
        self.path = Path(self.dir.name) / 'profile.json'
        self.path.write_text(json.dumps(PROJECT))
        self.sha = hashlib.sha256(self.path.read_bytes()).hexdigest()

    def tearDown(self):
        self.dir.cleanup()

    def test_reads_pinned_profile(self):
        self.assertEqual(self.read(self.path, self.sha).source_digest, PROJECT['source_digest'])

    def test_rejects_unpinned_or_changed_bytes(self):
        with self.assertRaisesRegex(ValueError, 'pinned SHA-256'):
            self.read(self.path, '0' * 64)
        with self.assertRaisesRegex(ValueError, '64 lowercase hex'):
            self.read(self.path, 'abc')

    def test_rejects_non_json_without_echoing_content(self):
        self.path.write_bytes(b'secret-not-json')
        sha = hashlib.sha256(b'secret-not-json').hexdigest()
        with self.assertRaises(ValueError) as cm:
            self.read(self.path, sha)
        self.assertNotIn('secret', str(cm.exception))

    def test_rejects_oversized_file(self):
        from app.infrastructure.lsys import MAX_PROFILE_BYTES
        self.path.write_bytes(b' ' * (MAX_PROFILE_BYTES + 1))
        with self.assertRaisesRegex(ValueError, 'size limit'):
            self.read(self.path, self.sha)


class DesignPage(unittest.TestCase):
    def test_doc_examples_run(self):
        result = doctest.testfile(str(ROOT / 'docs/domain/LSYS_DOMAIN_VOCABULARY.md'), module_relative=False)
        self.assertGreater(result.attempted, 0)
        self.assertEqual(result.failed, 0)


class Layering(unittest.TestCase):
    def test_application_lsys_is_pure(self):
        files = py_files('application/lsys')
        self.assertTrue(files)
        for f in files:
            mods = imports(f)
            self.assertFalse({m for m in mods if m.split('.')[0] in HEAVY}, f.name)
            self.assertFalse({m for m in mods if m.startswith(('app.infrastructure', 'app.interfaces', 'fastapi'))}, f.name)
            text = f.read_text()
            for banned in ('open(', 'eval(', 'exec(', 'pathlib', 'import os'):
                self.assertNotIn(banned, text, f.name)

    def test_infrastructure_lsys_never_imports_interfaces(self):
        for f in py_files('infrastructure/lsys'):
            self.assertFalse({m for m in imports(f) if m.startswith(('app.interfaces', 'fastapi'))}, f.name)


if __name__ == '__main__':
    unittest.main()
