import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

import doctest
import subprocess

from pydantic import ValidationError

from app.application.simulation import contracts as C
from app.application.simulation import services, tensors
from app.application.simulation.tensors import TensorContractError, TensorRef, TensorSpec, TensorStats, check_bindings

Z = "0" * 64


def ref(spec, shape, key=None):
    return TensorRef(spec=spec, key=key or f"{spec.name}/x", shape=shape, sha256=Z, producer="test")


class Specs(unittest.TestCase):
    def test_dims_shape_length_must_match(self):
        with self.assertRaises(ValidationError):
            TensorSpec(name="a", dims=("node",), shape=("N", 2), dtype="float32", description="a")

    def test_bad_symbol_and_dtype(self):
        with self.assertRaises(ValidationError):
            TensorSpec(name="a", dims=("node",), shape=("n",), dtype="float32", description="a")
        with self.assertRaises(ValidationError):
            TensorSpec(name="a", dims=("node",), shape=("N",), dtype="float16", description="a")

    def test_ref_rejects_shape_that_breaks_spec(self):
        s = C.NodeInteractionResult.TENSORS["node_velocity"]
        with self.assertRaises(ValidationError):
            ref(s, (4, 3, 3))  # last axis must be 2

    def test_repeated_symbol_binds_once(self):
        s = C.NodeInteractionResult.TENSORS["field"]
        with self.assertRaises(ValidationError):
            ref(s, (4, 5, 16, 15))

    def test_cross_tensor_binding(self):
        s = C.NodeInteractionResult.TENSORS
        with self.assertRaises(TensorContractError):
            check_bindings({"coupling": ref(s["coupling"], (3, 3)), "node_velocity": ref(s["node_velocity"], (2, 4, 2))})


def _slice(inflow, saddles=0):
    pts = tuple(C.CriticalPoint(x=0.1 * i, y=0, kind=C.PointKind.SADDLE, det=-1, trace=-0.1) for i in range(saddles))
    pts += (C.CriticalPoint(x=1, y=1, kind=C.PointKind.SPIRAL_SINK, det=1, trace=-0.1),)
    return C.InflowSlice(inflow=inflow, saddle_count=saddles, core_count=1, points=pts)


class Results(unittest.TestCase):
    def setUp(self):
        s = C.NodeInteractionResult.TENSORS
        self.kw = dict(frame_id="f", request_digest=Z, n_nodes=3, grid=C.FieldGrid(size=8),
                       slices=(_slice(0.0), _slice(0.1, 1)),
                       coupling=ref(s["coupling"], (3, 3)), node_velocity=ref(s["node_velocity"], (2, 3, 2)),
                       field=ref(s["field"], (2, 5, 8, 8)))

    def test_valid_result(self):
        r = C.NodeInteractionResult(**self.kw)
        self.assertEqual(r.saddle_curve, (0, 1))
        self.assertEqual(r.result_kind, "embedding_geometry")

    def test_n_nodes_must_bind(self):
        with self.assertRaises(ValidationError):
            C.NodeInteractionResult(**{**self.kw, "n_nodes": 4})

    def test_slice_count_must_bind(self):
        with self.assertRaises(ValidationError):
            C.NodeInteractionResult(**{**self.kw, "slices": (_slice(0.0),)})

    def test_spec_drift_rejected(self):
        drift = C.NodeInteractionResult.TENSORS["coupling"].model_copy(update={"unit": "other"})
        with self.assertRaises(ValidationError):
            C.NodeInteractionResult(**{**self.kw, "coupling": ref(drift, (3, 3))})

    def test_field_presence_follows_grid(self):
        with self.assertRaises(ValidationError):
            C.NodeInteractionResult(**{**self.kw, "grid": None})

    def test_slice_counts_match_points(self):
        with self.assertRaises(ValidationError):
            C.InflowSlice(inflow=0, saddle_count=2, core_count=0, points=())

    def test_ring_shares_must_conserve(self):
        s = C.BufferRingResult.TENSORS
        ring = C.BufferRing(index=0, core_x=0, core_y=0, spiral=True, radius=0.1, occupancy=16, share=0.25)
        base = dict(frame_id="f", request_digest=Z, inflow=0.07, grid=C.FieldGrid(size=8), tracers=64, history_len=4,
                    history_filled=4, rings=(ring,), basins=ref(s["basins"], (8, 8)),
                    occupancy_history=ref(s["occupancy_history"], (1, 4)), tracers_final=ref(s["tracers_final"], (64, 2)))
        with self.assertRaises(ValidationError):
            C.BufferRingResult(**base, unassigned_share=0.5)
        self.assertEqual(C.BufferRingResult(**base, unassigned_share=0.75).rings[0].occupancy, 16)

    def test_graph_feature_count_binds(self):
        s = C.GraphSample.TENSORS
        kw = dict(frame_id="f", inflow=0.07, edge_rule="knn", node_ids=("a", "b"),
                  edge_index=ref(s["edge_index"], (2, 2)), edge_attr=ref(s["edge_attr"], (2, len(C.EDGE_FEATURES))))
        C.GraphSample(**kw, x=ref(s["x"], (2, len(C.NODE_FEATURES))))
        with self.assertRaises(ValidationError):
            C.GraphSample(**kw, x=ref(s["x"], (2, 3)))


class Requests(unittest.TestCase):
    def test_sweep_rules(self):
        self.assertEqual(len(C.InflowSweep.grid(0, 0.3, 0.02).values), 16)
        for bad in ((0.1, 0.1), (0.2, 0.1), (1.5,)):
            with self.assertRaises(ValidationError):
                C.InflowSweep(values=bad)

    def test_node_rules(self):
        n = C.InteractionNode(id="a", x=0, y=0, strength=0.3)
        with self.assertRaises(ValidationError):
            C.NodeInteractionRequest(frame_id="f", nodes=(n, n), inflow=C.InflowSweep(values=(0.1,)))
        with self.assertRaises(ValidationError):
            C.InteractionNode(id="b", x=float("nan"), y=0, strength=1)
        with self.assertRaises(ValidationError):
            C.NodeInteractionRequest(frame_id="f", nodes=(n.model_copy(update={"strength": 0.0}),), inflow=C.InflowSweep(values=(0.1,)))

    def test_digest_is_stable_and_sensitive(self):
        n = C.InteractionNode(id="a", x=0, y=0, strength=0.3)
        a = C.NodeInteractionRequest(frame_id="f", nodes=(n,), inflow=C.InflowSweep(values=(0.1,)))
        self.assertEqual(a.digest(), a.model_copy().digest())
        self.assertNotEqual(a.digest(), a.model_copy(update={"frame_id": "g"}).digest())

    def test_transform_params(self):
        with self.assertRaises(ValidationError):
            C.TransformSpec(op="select_slices")
        with self.assertRaises(ValidationError):
            C.TransformSpec(op="astype")

    def test_contracts_are_frozen(self):
        n = C.InteractionNode(id="a", x=0, y=0, strength=0.3)
        with self.assertRaises(ValidationError):
            n.x = 1.0


class Documentation(unittest.TestCase):
    def test_every_field_is_described(self):
        models = list(C.CONTRACTS) + [C.CriticalPoint, C.InflowSlice, C.CollisionEvent, C.BufferRing, TensorRef, TensorStats, TensorSpec]
        missing = [f"{m.__name__}.{n}" for m in models for n, f in m.model_fields.items() if not f.description]
        self.assertEqual(missing, [], "add Field(description=...) so the generated docs stay complete")

    def test_every_tensor_contract_documents_its_producer(self):
        for m in C.TENSOR_CONTRACTS:
            self.assertTrue(m.PRODUCED_BY and m.TENSORS, m.__name__)

    def test_generated_docs_are_current(self):
        r = subprocess.run([sys.executable, str(ROOT / "scripts" / "gen_contract_docs.py"), "--check"], capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)

    def test_module_doctests(self):
        for mod in (tensors, services):
            self.assertEqual(doctest.testmod(mod).failed, 0, mod.__name__)


if __name__ == "__main__":
    unittest.main()
