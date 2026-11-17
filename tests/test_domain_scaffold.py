"""Scaffold integrity: imports, two-field schemas, fail-closed guard, layering. Not semantic acceptance."""
import ast, doctest, importlib, json, sys, unittest
from pathlib import Path
from uuid import uuid4

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
from pydantic import ValidationError  # noqa: E402

ENTRIES = json.loads((ROOT / "docs/domain/domain_scaffold_manifest.json").read_text())["entries"]
DOMAIN = ROOT / "src/app/domain"


class DomainScaffold(unittest.TestCase):
    def test_population(self):
        self.assertEqual(len(ENTRIES), 94)
        self.assertEqual(len({e["class_name"] for e in ENTRIES}), 94)
        self.assertEqual(sum(e["source"] == "addition" for e in ENTRIES), 12)

    def test_every_class_is_fail_closed(self):
        for e in ENTRIES:
            with self.subTest(cls=e["class_name"]):
                cls = getattr(importlib.import_module(e["module"]), e["class_name"])
                obj = cls()
                self.assertEqual((obj.entity_id, obj.definition_status), (None, "unreviewed-scaffold"))
                self.assertEqual(set(cls.model_fields), {"entity_id", "definition_status"})
                self.assertFalse(cls.model_json_schema()["additionalProperties"])
                self.assertEqual(cls.model_validate_json(cls(entity_id=uuid4()).model_dump_json()).definition_status, "unreviewed-scaffold")
                with self.assertRaises(NotImplementedError):
                    obj.require_accepted_definition()
                for bad in ({"definition_status": "approved"}, {"approval_authority": True}, {"entity_id": "PO-12345"}):
                    with self.assertRaises(ValidationError):
                        cls(**bad)

    def test_no_inheritance_between_scaffolds_and_pure_imports(self):
        for f in DOMAIN.rglob("*.py"):
            tree = ast.parse(f.read_text())
            mods = {n.module for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)} | {a.name for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names}
            self.assertFalse({m for m in mods if m and m.split(".")[0] in {"numpy", "torch", "scipy"}}, f.name)
            self.assertFalse({m for m in mods if m and m.startswith("app.infrastructure")}, f.name)
            for c in (n for n in tree.body if isinstance(n, ast.ClassDef)):
                if c.name != "ScaffoldRecord":
                    self.assertEqual([ast.unparse(b) for b in c.bases], ["ScaffoldRecord"], f"{f.name}:{c.name}")

    def test_doc_example(self):
        self.assertEqual(doctest.testfile(str(ROOT / "docs/domain/DOMAIN_SCAFFOLD.md"), module_relative=False).failed, 0)


if __name__ == "__main__":
    unittest.main()
