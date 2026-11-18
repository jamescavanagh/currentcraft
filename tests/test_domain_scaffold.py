"""Historical import compatibility, placeholders and V1 proposal layering."""
import ast, doctest, importlib, json, sys, unittest
from pathlib import Path
from uuid import uuid4
from pydantic import ValidationError

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / 'src'))
ENTRIES = json.loads((ROOT / 'docs/domain/domain_scaffold_manifest.json').read_text())['entries']
DOMAIN = ROOT / 'src/app/domain'


class DomainScaffold(unittest.TestCase):
    def test_population(self):
        self.assertEqual(len(ENTRIES), 94)
        self.assertEqual(len({e['class_name'] for e in ENTRIES}), 94)
        self.assertEqual(sum(e['source'] == 'addition' for e in ENTRIES), 12)

    def test_every_historical_import_is_preserved_and_unreviewed(self):
        for e in ENTRIES:
            with self.subTest(cls=e['class_name']):
                cls = getattr(importlib.import_module(e['module']), e['class_name'])
                self.assertIn(cls.SCHEMA_STATUS, {'unreviewed-scaffold', 'v1-proposal'})
                self.assertFalse(cls.model_json_schema()['additionalProperties'])
                if cls.SCHEMA_STATUS == 'v1-proposal':
                    with self.assertRaises(ValidationError):
                        cls()  # Explicitly documented migration: identity is now required.
                    continue
                obj = cls()
                self.assertEqual((obj.entity_id, obj.definition_status), (None, 'unreviewed-scaffold'))
                self.assertEqual(set(cls.model_fields), {'entity_id', 'definition_status'})
                self.assertEqual(cls.model_validate_json(obj.model_dump_json()), obj)
                with self.assertRaises(NotImplementedError):
                    obj.require_accepted_definition()
                for bad in ({'definition_status': 'approved'}, {'approval_authority': True}, {'entity_id': 'PO-12345'}):
                    with self.assertRaises(ValidationError):
                        cls(**bad)

    def test_domain_imports_allow_pydantic_but_no_runtime_dependencies(self):
        forbidden = {'numpy','torch','scipy','fastapi','starlette','uvicorn','psycopg','sqlalchemy','pathlib','os','socket','requests','httpx','importlib'}
        for f in DOMAIN.rglob('*.py'):
            tree = ast.parse(f.read_text())
            mods = {n.module for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)} | {a.name for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names}
            self.assertFalse({m for m in mods if m and m.split('.')[0] in forbidden}, f.name)
            self.assertFalse({m for m in mods if m and m.startswith(('app.infrastructure', 'app.application', 'app.interfaces'))}, f.name)

    def test_doc_example(self):
        self.assertEqual(doctest.testfile(str(ROOT / 'docs/domain/DOMAIN_SCAFFOLD.md'), module_relative=False).failed, 0)


if __name__ == '__main__':
    unittest.main()
