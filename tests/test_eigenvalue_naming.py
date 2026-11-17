"""0.9.8: Jacobian eigenvalues are mu; lambda only ever means inflow.

The contract field lambda_min_abs became mu_min_abs and the simulation schema moved to datamesh-sim/v2.
v1 payloads still read (old key accepted, version upgraded on input); output is always v2 with mu_min_abs.
"""
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from pydantic import ValidationError

from app.application.simulation import contracts as C
from app.infrastructure.tensors import numpy_kernels as K

import numpy as np

# Two co-rotating vortices: one saddle between them at any inflow > 0.
V = np.array([[-0.5, 0.0, 1.0], [0.5, 0.0, 1.0]])


def _point(**kw):
    base = dict(x=0.0, y=0.0, kind="saddle", det=-1.0, trace=0.0)
    base.update(kw)
    return base


class EigenvalueName(unittest.TestCase):
    def test_kernel_emits_mu_and_never_lambda(self):
        pts = K.critical_points(V, inflow=0.1, softening=0.02, scale=6.0)
        saddles = [q for q in pts if q["kind"] == "saddle"]
        self.assertTrue(saddles)
        for q in pts:
            self.assertIn("mu_min_abs", q)
            self.assertNotIn("lambda_min_abs", q)
        for q in saddles:
            disc = (q["trace"] ** 2 - 4 * q["det"]) ** 0.5
            self.assertAlmostEqual(q["mu_min_abs"], min(abs((q["trace"] + disc) / 2), abs((q["trace"] - disc) / 2)))
        self.assertTrue(all(q["mu_min_abs"] is None for q in pts if q["kind"] != "saddle"))

    def test_contract_field_is_mu(self):
        self.assertIn("mu_min_abs", C.CriticalPoint.model_fields)
        self.assertNotIn("lambda_min_abs", C.CriticalPoint.model_fields)
        self.assertEqual(list(C.CriticalPoint.model_json_schema()["properties"]).count("mu_min_abs"), 1)

    def test_legacy_key_reads_and_writes_back_as_mu(self):
        old = C.CriticalPoint.model_validate(_point(lambda_min_abs=0.5))
        new = C.CriticalPoint(**_point(mu_min_abs=0.5))
        self.assertEqual(old, new)
        out = json.loads(old.model_dump_json())
        self.assertEqual(out["mu_min_abs"], 0.5)
        self.assertNotIn("lambda_min_abs", out)

    def test_both_keys_is_ambiguous_and_rejected(self):
        with self.assertRaises(ValidationError):
            C.CriticalPoint.model_validate(_point(lambda_min_abs=0.5, mu_min_abs=0.4))


class SchemaVersion(unittest.TestCase):
    def test_current_version_is_v2(self):
        self.assertEqual(C.SCHEMA_VERSION, "datamesh-sim/v2")
        r = C.NodeInteractionRequest(frame_id="f", nodes=(C.InteractionNode(id="a", x=0, y=0, strength=0.3),),
                                     inflow=C.InflowSweep(values=(0.1,)))
        self.assertEqual(r.schema_version, "datamesh-sim/v2")

    def test_v1_reads_and_is_upgraded(self):
        n = C.InteractionNode(id="a", x=0, y=0, strength=0.3)
        v1 = C.NodeInteractionRequest.model_validate({"schema_version": "datamesh-sim/v1", "frame_id": "f",
                                                      "nodes": [n.model_dump()], "inflow": {"values": [0.1]}})
        self.assertEqual(v1.schema_version, "datamesh-sim/v2")
        v2 = C.NodeInteractionRequest(frame_id="f", nodes=(n,), inflow=C.InflowSweep(values=(0.1,)))
        self.assertEqual(v1.digest(), v2.digest())

    def test_unknown_version_rejected(self):
        with self.assertRaises(ValidationError):
            C.NodeInteractionRequest.model_validate({"schema_version": "datamesh-sim/v3", "frame_id": "f",
                                                     "nodes": [{"id": "a", "x": 0, "y": 0, "strength": 0.3}],
                                                     "inflow": {"values": [0.1]}})


class NoEigenvalueLambdaLeft(unittest.TestCase):
    def test_simulation_sources_and_generated_docs_use_mu(self):
        roots = [ROOT / "src/app/application/simulation", ROOT / "src/app/infrastructure/tensors"]
        hits = []
        for root in roots:
            for p in root.rglob("*.py"):
                text = p.read_text()
                for line in text.splitlines():
                    if "lambda_min_abs" in line and "AliasChoices" not in line and "pre-0.9.8" not in line:
                        hits.append(f"{p.relative_to(ROOT)}: {line.strip()}")
        for p in (ROOT / "docs/contracts").rglob("*"):
            if p.is_file() and "lambda_min_abs" in p.read_text() and "pre-0.9.8" not in p.read_text():
                hits.append(str(p.relative_to(ROOT)))
        self.assertEqual(hits, [])


if __name__ == "__main__":
    unittest.main()
