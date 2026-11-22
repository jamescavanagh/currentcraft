"""Synthetic checks for the compiled 0.11 feature-graph query path."""
import unittest
from unittest.mock import patch

from app.application.feature_graph.services import validate_configuration
from app.domain.operand.feature_graph import FeatureConstraint
from app.infrastructure.feature_graph import build_memory_feature_graph
from tests.test_feature_graph import evidence, feature, graph, observation, request, uid


class FeatureGraphQueryIndexTests(unittest.TestCase):
    def setUp(self):
        self.service, self.repository = build_memory_feature_graph()

    def test_append_builds_reusable_exact_revision_index(self):
        snapshot = graph()
        self.service.append(snapshot, expected_revision=0)
        key = (snapshot.graph_id, snapshot.revision)
        self.assertIs(self.repository.get_revision(*key), snapshot)
        index = self.repository.query_index(*key)
        self.assertIsNotNone(index)
        self.assertIs(self.repository.query_index(*key), index)
        self.assertEqual(index.graph_digest, snapshot.digest())

    def test_indexed_service_matches_standalone_evaluation_without_history_scan(self):
        constraints = (
            FeatureConstraint(constraint_id=uid(701), kind="requires", left=uid(1), right=uid(2), provenance=evidence(701)),
            FeatureConstraint(constraint_id=uid(702), kind="excludes", left=uid(2), right=uid(4), provenance=evidence(702)),
        )
        snapshot = graph(
            features=(feature(1), feature(2), feature(3, mandatory=True), feature(4)),
            constraints=constraints,
            observations=(observation(present=(1, 2, 3)),),
        )
        self.service.append(snapshot, expected_revision=0)
        good_request = request(snapshot, (1, 2, 3))
        bad_request = request(snapshot, (1, 2, 3, 4))

        with patch.object(self.repository, "history", side_effect=AssertionError("validation scanned full history")):
            indexed_good = self.service.validate(good_request)
            indexed_bad = self.service.validate(bad_request)

        self.assertEqual(indexed_good, validate_configuration(snapshot, good_request))
        self.assertEqual(indexed_bad, validate_configuration(snapshot, bad_request))
        self.assertEqual(indexed_good.evidence_status, "observed_configuration")
        self.assertEqual(indexed_bad.model_outcome, "violates_model")
        self.assertTrue(any(code.startswith("excludes:") for code in indexed_bad.violations))

    def test_cached_index_collections_are_read_only(self):
        snapshot = graph()
        self.service.append(snapshot, expected_revision=0)
        index = self.repository.query_index(snapshot.graph_id, snapshot.revision)
        with self.assertRaises(TypeError):
            index.constraints_by_left[uid(999)] = ()
        with self.assertRaises(TypeError):
            index.complete_observations_by_selection[frozenset()] = ()


if __name__ == "__main__":
    unittest.main()
