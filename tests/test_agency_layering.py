import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from tests.test_simulation_layering import HEAVY, imports, py_files  # noqa: E402

APP = ("application/process", "application/plate", "application/messaging", "application/enrichment", "application/probe", "application/ingest", "application/persistence", "application/splice", "application/hfgt", "application/common")


class AgencyLayering(unittest.TestCase):
    def test_application_slices_are_numpy_free_and_never_import_infrastructure(self):
        for rel in APP:
            files = py_files(rel)
            self.assertTrue(files, rel)
            for f in files:
                mods = imports(f)
                self.assertFalse({m for m in mods if m.split(".")[0] in HEAVY}, f"{f.name} imports numeric libs")
                self.assertFalse({m for m in mods if m.startswith(("app.infrastructure", "infrastructure"))}, f.name)
                text = f.read_text(encoding="utf-8")
                self.assertNotIn("arbitrary_types_allowed", text, f.name)
                self.assertNotIn("ndarray", text, f.name)

    def test_process_slice_does_not_depend_on_plate_or_messaging(self):
        for f in py_files("application/process"):
            self.assertFalse({m for m in imports(f) if m.startswith(("app.application.plate", "app.application.messaging"))}, f.name)

    def test_messaging_infrastructure_is_pure_python(self):
        for f in py_files("infrastructure/messaging"):
            self.assertFalse({m for m in imports(f) if m.split(".")[0] in HEAVY}, f.name)

    def test_probe_infrastructure_uses_numpy_only(self):
        files = py_files("infrastructure/probe")
        self.assertTrue([f for f in files if "numpy" in imports(f)])
        for f in files:
            self.assertFalse({m for m in imports(f) if m.split(".")[0] in HEAVY - {"numpy"}}, f.name)

    def test_enrichment_infrastructure_uses_numpy_only(self):
        files = py_files("infrastructure/enrichment")
        self.assertTrue([f for f in files if "numpy" in imports(f)])
        for f in files:
            self.assertFalse({m for m in imports(f) if m.split(".")[0] in HEAVY - {"numpy"}}, f.name)

    def test_ingest_infrastructure_uses_numpy_only(self):
        files = py_files("infrastructure/ingest")
        self.assertTrue([f for f in files if "numpy" in imports(f)])
        for f in files:
            self.assertFalse({m for m in imports(f) if m.split(".")[0] in HEAVY - {"numpy"}}, f.name)

    def test_ingest_application_never_reads_bytes_or_imports_parsers(self):
        for f in py_files("application/ingest"):
            mods = {m.split(".")[0] for m in imports(f)}
            self.assertFalse(mods & {"email", "zipfile", "pypdf", "xml", "json"}, f.name)

    def test_splice_infrastructure_uses_numpy_only(self):
        files = py_files("infrastructure/splice")
        self.assertTrue([f for f in files if "numpy" in imports(f)])
        for f in files:
            self.assertFalse({m for m in imports(f) if m.split(".")[0] in HEAVY - {"numpy"}}, f.name)

    def test_splice_application_never_imports_the_simulator_or_probe(self):
        # 0.9.9: the simulator is now checked too (the shared base moved to app.application.common)
        for f in py_files("application/splice"):
            self.assertFalse({m for m in imports(f) if m.startswith(("app.application.probe", "app.application.plate",
                                                                     "app.application.simulation"))}, f.name)

    def test_common_imports_no_slice(self):
        for f in py_files("application/common"):
            self.assertFalse({m for m in imports(f) if m.startswith("app.")}, f.name)

    def test_hfgt_application_uses_only_tensor_descriptors_from_the_simulator(self):
        allowed = {"app.application.simulation.contracts", "app.application.simulation.tensors"}
        for f in py_files("application/hfgt"):
            sim = {m for m in imports(f) if m.startswith("app.application.simulation")}
            self.assertFalse(sim - allowed, f.name)
            self.assertNotIn("SimulationService", f.read_text(encoding="utf-8"), f.name)

    def test_hfgt_infrastructure_uses_numpy_only(self):
        files = py_files("infrastructure/hfgt")
        self.assertTrue([f for f in files if "numpy" in imports(f)])
        for f in files:
            self.assertFalse({m for m in imports(f) if m.split(".")[0] in HEAVY - {"numpy"}}, f.name)

    def test_plate_infrastructure_uses_numpy_only(self):
        files = py_files("infrastructure/plate")
        self.assertTrue([f for f in files if "numpy" in imports(f)])
        for f in files:
            self.assertFalse({m for m in imports(f) if m.split(".")[0] in HEAVY - {"numpy"}}, f.name)


if __name__ == "__main__":
    unittest.main()
