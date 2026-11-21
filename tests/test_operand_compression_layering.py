import ast
import importlib.util
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parent.parent
HEAVY = {"numpy", "scipy", "torch", "pandas", "jax", "tensorflow", "numba", "cupy", "torch_geometric", "dgl"}


def imports(path):
    found = set()
    for node in ast.walk(ast.parse(path.read_text(), filename=str(path))):
        if isinstance(node, ast.Import):
            found.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            found.add(node.module)
    return found


class SixDomainBoundaryTests(unittest.TestCase):
    def test_domain_and_application_are_array_free(self):
        for rel in ("domain/operand", "application/operand_compression", "application/feature_graph"):
            paths = list((ROOT / "src/app" / rel).glob("*.py"))
            self.assertTrue(paths, rel)
            for path in paths:
                self.assertFalse({name for name in imports(path) if name.split(".")[0] in HEAVY}, path.name)

    def test_directional_layer_boundaries(self):
        for layer, packages, forbidden in (
            ("domain", ("operand",), ("app.application", "app.infrastructure", "app.interfaces")),
            ("application", ("operand_compression", "feature_graph"), ("app.infrastructure", "app.interfaces")),
            ("infrastructure", ("operand_compression", "feature_graph"), ("app.interfaces", "fastapi", "starlette", "uvicorn"))):
            for package in packages:
                paths = list((ROOT / "src/app" / layer / package).glob("*.py"))
                self.assertTrue(paths, package)
                for path in paths:
                    self.assertFalse({name for name in imports(path) if name.startswith(forbidden)}, path.name)

    def test_generated_reference_has_no_drift(self):
        spec = importlib.util.spec_from_file_location("feature_graph_docs", ROOT / "scripts/gen_feature_graph_docs.py")
        generator = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(generator)
        self.assertEqual(generator.OUT.read_text(), generator.render())

    def test_schema_contains_six_domain_contracts(self):
        spec = importlib.util.spec_from_file_location("feature_graph_schema", ROOT / "scripts/gen_feature_graph_docs.py")
        generator = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(generator)
        definitions = generator.schema()["$defs"]
        for model in generator.CONTRACTS:
            self.assertIn(model.__name__, definitions)
            for field in model.model_fields.values():
                self.assertTrue(field.description)


if __name__ == "__main__":
    unittest.main()
