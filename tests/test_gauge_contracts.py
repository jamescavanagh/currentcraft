import doctest
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from pydantic import ValidationError  # noqa: E402

from app.application.gauge import contracts as G  # noqa: E402
from app.application.gauge import services as S  # noqa: E402
from app.application.simulation.contracts import NodeRole  # noqa: E402
from app.application.simulation.tensors import TensorRef, TensorSpec  # noqa: E402


def emb_ref(n=8, k=4, spec=G.EMBEDDINGS_SPEC):
    return TensorRef(spec=spec, key="gauge.embeddings/x", shape=(n, k), sha256="0" * 64, producer="test")


def nodes(n=8, **kw):
    return tuple(G.GaugeNode(id=f"n{i}", **kw) for i in range(n))


def req(**kw):
    base = dict(frame_id="synthetic-example", space=G.EmbeddingSpaceRef(model="m"), nodes=nodes(), embeddings=emb_ref(),
                params=G.GaugeParams(k=4))
    base.update(kw)
    return G.GaugeRequest(**base)


class Requests(unittest.TestCase):
    def test_valid_request_and_stable_digest(self):
        r = req()
        self.assertEqual(r.schema_version, "datamesh-gauge/v1")
        self.assertEqual(r.result_kind, "embedding_geometry")
        self.assertEqual(r.digest(), req().digest())
        self.assertIs(r.nodes[0].role, NodeRole.UNASSIGNED)

    def test_rejects_bad_requests(self):
        cases = {
            "duplicate": dict(nodes=nodes()[:7] + (G.GaugeNode(id="n0"),)),
            "row count": dict(embeddings=emb_ref(n=9)),
            "too few dims": dict(embeddings=emb_ref(k=2)),
            "k >= n": dict(params=G.GaugeParams(k=8)),
            "wrong spec": dict(embeddings=emb_ref(spec=TensorSpec(name="other", dims=("node", "embedding"), shape=("N", "K"),
                                                                   dtype="float64", description="x"))),
            "unknown loop id": dict(loops=(G.GaugeLoop(id="l", node_ids=("n0", "n1", "zz")),)),
            "supply_demand without both sides": dict(params=G.GaugeParams(k=4, director_mode="supply_demand")),
        }
        for name, kw in cases.items():
            with self.subTest(name), self.assertRaises(ValidationError):
                req(**kw)

    def test_supply_demand_needs_both_sides(self):
        ns = tuple(G.GaugeNode(id=f"n{i}", flow=G.FlowSide.SUPPLY if i % 2 else G.FlowSide.DEMAND) for i in range(8))
        self.assertEqual(req(nodes=ns, params=G.GaugeParams(k=4, director_mode="supply_demand")).params.charge_quantum, 1.0)


class Results(unittest.TestCase):
    def _refs(self, N=8, E=3, T=1):
        shapes = {"node_gauges": (N, len(G.NODE_GAUGE_FEATURES)), "node_mask": (N,), "director": (N,), "edge_index": (2, E),
                  "edge_connection": (E,), "edge_link": (E,), "edge_reliability": (E,), "triangles": (3, T),
                  "triangle_holonomy": (T,), "triangle_charge": (T,), "triangle_z2": (T,)}
        return {n: TensorRef(spec=s, key=f"{s.name}/x", shape=shapes[n], sha256="0" * 64, producer="t") for n, s in G.GaugeResult.TENSORS.items()}

    def _result(self, refs, **kw):
        base = dict(frame_id="f", request_digest="1" * 64, embeddings_sha256="2" * 64, director_mode="principal_axis",
                    charge_quantum=0.5, node_ids=tuple(f"n{i}" for i in range(8)), n_valid=8, n_links=3, n_triangles=1,
                    orientation_conflicts=0)
        base.update(kw)
        return G.GaugeResult(**base, **refs)

    def test_bindings_enforced(self):
        self._result(self._refs())
        with self.assertRaises(ValidationError):
            self._result(self._refs(E=4))           # n_links says 3
        with self.assertRaises(ValidationError):
            self._result(self._refs(), charge_quantum=1.0)

    def test_gauge_dependent_split(self):
        self.assertEqual(set(G.GaugeResult.GAUGE_DEPENDENT), {"director", "edge_connection"})
        self.assertNotIn("edge_connection", G.GaugeResult.invariant_tensors())
        self.assertIn("triangle_charge", G.GaugeResult.invariant_tensors())

    def test_null_request_needs_both_labels(self):
        e = (G.ParticipationEdge(resource_id="a", process_id="p", stage="s"), G.ParticipationEdge(resource_id="b", process_id="p", stage="s"))
        only_pos = (G.ScoredPair(a="a", b="b", stage="s", local_score=1, global_score=1),
                    G.ScoredPair(a="b", b="a", stage="s", local_score=1, global_score=1))
        with self.assertRaises(ValidationError):
            G.StageNullRequest(frame_id="f", participation=e, pairs=only_pos)
        with self.assertRaises(ValidationError):
            G.StageNullRequest(frame_id="f", participation=e, pairs=only_pos[:1] + (G.ScoredPair(a="a", b="c", stage="other", local_score=0, global_score=0),))


class Documentation(unittest.TestCase):
    def test_every_field_is_described(self):
        missing = [f"{m.__name__}.{n}" for m in G.CONTRACTS for n, f in m.model_fields.items() if not f.description]
        self.assertEqual(missing, [])

    def test_every_tensor_contract_documents_its_producer(self):
        for m in G.TENSOR_CONTRACTS:
            self.assertTrue(m.PRODUCED_BY and m.TENSORS, m.__name__)

    def test_every_feature_has_a_meaning(self):
        self.assertEqual(set(G.NODE_GAUGE_FEATURES), set(G.NODE_GAUGE_MEANINGS))

    def test_generated_docs_are_current(self):
        r = subprocess.run([sys.executable, str(ROOT / "scripts" / "gen_gauge_contract_docs.py"), "--check"], capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)

    def test_module_doctests(self):
        for mod in (G, S):
            self.assertEqual(doctest.testmod(mod).failed, 0, mod.__name__)


if __name__ == "__main__":
    unittest.main()
