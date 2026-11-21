import ast
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
HEAVY = {"numpy", "scipy", "torch", "pandas", "jax", "tensorflow", "numba", "cupy", "torch_geometric", "dgl"}


def imports(path):
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    found = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            found.add(node.module)
    return found


class OperandCompressionLayeringTests(unittest.TestCase):
    def test_domain_and_application_are_array_free(self):
        for rel in ("domain/operand", "application/operand_compression"):
            for path in (ROOT / "src/app" / rel).rglob("*.py"):
                bad = {name for name in imports(path) if name.split(".")[0] in HEAVY}
                self.assertFalse(bad, f"{path.relative_to(ROOT)} imports {sorted(bad)}")

    def test_application_never_imports_infrastructure(self):
        for path in (ROOT / "src/app/application/operand_compression").rglob("*.py"):
            bad = {name for name in imports(path) if name.startswith(("app.infrastructure", "infrastructure"))}
            self.assertFalse(bad, f"{path.relative_to(ROOT)} imports {sorted(bad)}")


if __name__ == "__main__":
    unittest.main()
