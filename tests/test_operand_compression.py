import sys
import unittest
from pathlib import Path
from uuid import UUID

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from pydantic import ValidationError
from app.domain.operand import FormationSet, OperandProfile, OperandRef, ProfileLayer
from app.application.gauge.contracts import EMBEDDINGS_SPEC, EmbeddingSpaceRef, GaugeParams
from app.application.operand_compression import OperandCompressionRequest
from app.application.simulation.tensors import TensorRef


class OperandProfileTests(unittest.TestCase):
    def test_people_and_client_parties_are_not_operands(self):
        for kind in ("employee", "contributor", "person", "client", "party", "resource"):
            with self.subTest(kind=kind), self.assertRaises(ValidationError):
                OperandRef(object_id=UUID(int=1), object_kind=kind, domain_context="employees_contributors")

    def test_timecards_are_not_a_domain_context(self):
        with self.assertRaises(ValidationError):
            OperandRef(object_id=UUID(int=1), object_kind="subsystem", domain_context="timecards")

    def test_formation_set_must_reference_supported_horizon_layers(self):
        evidence = UUID(int=4)
        operand = OperandRef(object_id=UUID(int=1), object_kind="subsystem", domain_context="subsystems")
        inherited = ProfileLayer(layer_id="stratum-a", order=0, kind="inherited_layer", evidence_ids=(evidence,))
        formation = FormationSet(period_ref="period-a", layer_ids=("stratum-a",), evidence_ids=(evidence,))
        with self.assertRaises(ValidationError):
            OperandProfile(profile_id="profile-a", operand=operand, projection_ref="projection/v1",
                           layers=(inherited,), formation_sets=(formation,))


class CompressionContractTests(unittest.TestCase):
    def request(self):
        profiles = tuple(OperandProfile(profile_id=f"profile-{i}",
                                        operand=OperandRef(object_id=UUID(int=i + 1), object_kind="subsystem",
                                                           domain_context="subsystems"),
                                        projection_ref="projection/v1") for i in range(5))
        embeddings = TensorRef(spec=EMBEDDINGS_SPEC, key="test/embeddings", shape=(5, 3),
                               sha256="0" * 64, producer="test")
        return OperandCompressionRequest(frame_id="synthetic-frame",
                                         space=EmbeddingSpaceRef(model="synthetic", reduction="none"),
                                         profiles=profiles, embeddings=embeddings, params=GaugeParams(k=4))

    def test_existing_gauge_request_preserves_order_without_labels(self):
        request = self.request()
        adapted = request.as_gauge_request()
        self.assertEqual(adapted.embeddings, request.embeddings)
        self.assertEqual(tuple(n.id for n in adapted.nodes), tuple(str(x.operand.object_id) for x in request.profiles))
        self.assertTrue(all(n.role.value == "operand" and n.label is None for n in adapted.nodes))

    def test_embedding_rows_must_match_operands(self):
        req = self.request()
        bad_ref = TensorRef(spec=EMBEDDINGS_SPEC, key="test/wrong", shape=(6, 3),
                            sha256="1" * 64, producer="test")
        with self.assertRaises(ValidationError):
            OperandCompressionRequest(frame_id=req.frame_id, space=req.space, profiles=req.profiles,
                                      embeddings=bad_ref, params=req.params)


if __name__ == "__main__":
    unittest.main()
