import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

import ast

HEAVY = {"numpy", "scipy", "torch", "pandas", "jax", "tensorflow", "numba", "cupy", "torch_geometric", "dgl"}


def imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    out = set()
    for n in ast.walk(tree):
        if isinstance(n, ast.Import):
            out |= {a.name for a in n.names}
        elif isinstance(n, ast.ImportFrom) and n.module and n.level == 0:
            out.add(n.module)
    return out


def py_files(rel: str):
    return sorted((ROOT / "src" / "app" / rel).rglob("*.py"))


# Pre-existing violations in source that predates the simulation slice. Ratchet: new violations fail,
# and fixing one fails until it is removed here (so the list only shrinks). Tracked by the import task.
KNOWN_INFRA_IMPORTS = {}


class Layering(unittest.TestCase):
    def test_domain_and_application_never_import_numeric_libs(self):
        for rel in ("domain", "application"):
            for f in py_files(rel):
                bad = {m for m in imports(f) if m.split(".")[0] in HEAVY}
                self.assertFalse(bad, f"{f.relative_to(ROOT)} imports {sorted(bad)}")

    def test_application_never_imports_infrastructure(self):
        seen = {}
        for f in py_files("application"):
            rel = str(f.relative_to(ROOT / "src" / "app"))
            bad = {m for m in imports(f) if m.startswith(("app.infrastructure", "infrastructure"))}
            if bad:
                seen[rel] = bad
        for rel, bad in seen.items():
            self.assertLessEqual(bad, KNOWN_INFRA_IMPORTS.get(rel, set()), f"new layering violation in {rel}: {sorted(bad)}")
        for rel, known in KNOWN_INFRA_IMPORTS.items():
            self.assertEqual(seen.get(rel, set()), known, f"{rel} changed: update KNOWN_INFRA_IMPORTS (it should only shrink)")

    def test_simulation_slice_has_no_exceptions(self):
        for f in py_files("application/simulation"):
            bad = {m for m in imports(f) if m.startswith(("app.infrastructure", "infrastructure"))}
            self.assertFalse(bad, f"{f.name} imports {sorted(bad)}")

    def test_domain_never_imports_simulation_or_infrastructure(self):
        for f in py_files("domain"):
            bad = {m for m in imports(f) if m.startswith(("app.infrastructure", "infrastructure", "app.application.simulation"))}
            self.assertFalse(bad, f"{f.relative_to(ROOT)} imports {sorted(bad)}")

    def test_application_models_do_not_allow_arbitrary_types(self):
        for f in py_files("application/simulation"):
            self.assertNotIn("arbitrary_types_allowed", f.read_text(encoding="utf-8"), f.name)

    def test_numpy_is_actually_used_in_infrastructure(self):
        users = [f for f in py_files("infrastructure/tensors") if "numpy" in imports(f)]
        self.assertTrue(users, "expected numpy adapters under infrastructure/tensors")

    def test_ports_signatures_are_array_free(self):
        src = (ROOT / "src/app/application/simulation/ports.py").read_text(encoding="utf-8")
        self.assertNotIn("ndarray", src)


if __name__ == "__main__":
    unittest.main()
