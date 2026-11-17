import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from tests.test_simulation_layering import HEAVY, imports, py_files  # noqa: E402


class GaugeLayering(unittest.TestCase):
    def test_application_gauge_is_numpy_free(self):
        for f in py_files("application/gauge"):
            bad = {m for m in imports(f) if m.split(".")[0] in HEAVY}
            self.assertFalse(bad, f"{f.name} imports {sorted(bad)}")

    def test_application_gauge_never_imports_infrastructure(self):
        for f in py_files("application/gauge"):
            bad = {m for m in imports(f) if m.startswith(("app.infrastructure", "infrastructure"))}
            self.assertFalse(bad, f"{f.name} imports {sorted(bad)}")

    def test_application_gauge_models_do_not_allow_arbitrary_types(self):
        for f in py_files("application/gauge"):
            self.assertNotIn("arbitrary_types_allowed", f.read_text(encoding="utf-8"), f.name)

    def test_gauge_ports_are_array_free(self):
        self.assertNotIn("ndarray", (ROOT / "src/app/application/gauge/ports.py").read_text(encoding="utf-8"))
        self.assertNotIn("ndarray", (ROOT / "src/app/application/gauge/geodesic.py").read_text(encoding="utf-8"))

    def test_infrastructure_gauge_uses_numpy_but_not_scipy(self):
        files = py_files("infrastructure/gauge")
        self.assertTrue([f for f in files if "numpy" in imports(f)], "expected numpy kernels under infrastructure/gauge")
        for f in files:
            bad = {m for m in imports(f) if m.split(".")[0] in HEAVY - {"numpy"}}
            self.assertFalse(bad, f"{f.name} imports {sorted(bad)} (requirements-ci.txt pins numpy + pydantic only)")

    def test_domain_never_imports_gauge(self):
        for f in py_files("domain"):
            self.assertFalse({m for m in imports(f) if m.startswith("app.application.gauge")}, f.name)

    def test_public_slice_has_no_internal_navigation(self):
        for f in py_files("application/gauge") + py_files("infrastructure/gauge"):
            self.assertNotIn("NAV: CLICKUP", f.read_text(), f.name)


if __name__ == "__main__":
    unittest.main()
