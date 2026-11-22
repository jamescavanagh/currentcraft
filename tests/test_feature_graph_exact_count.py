"""Hand-enumerated synthetic oracle; no production counting API or authority."""
from datetime import datetime, timezone
from itertools import product
import unittest
from uuid import UUID

from pydantic import ValidationError

from app.application.feature_graph.contracts import ConfigurationRequest, ConfigurationResult
from app.domain.operand.feature_graph import (
    FeatureConstraint, FeatureDefinition, FeatureGraphRevision,
    ProductObservation, Provenance,
)
from app.infrastructure.feature_graph import build_memory_feature_graph


FEATURES = (1, 2, 3, 4)
# Derived by hand: 1 mandatory; 2 -> 3; not (3 and 4).
EXPECTED_ALLOWED = frozenset({(1,), (1, 4), (1, 3), (1, 2, 3)})
OBSERVATIONS = {(1, 3): UUID(int=201), (1, 2): UUID(int=202)}
STAMP = datetime(2020, 1, 1, tzinfo=timezone.utc)


def uid(number):
    return UUID(int=number)


def exact_count_fixture(*, mandatory=True, constrained=True):
    provenance = Provenance(
        evidence_id=uid(100), source_snapshot_id=uid(1100),
        captured_at=STAMP, method="human_label",
    )
    definitions = tuple(
        FeatureDefinition(
            feature_id=uid(number), version=1,
            definition_digest=f"{number:064x}", status="active",
            mandatory=mandatory and number == 1, provenance=provenance,
        )
        for number in FEATURES
    )
    constraints = tuple(
        FeatureConstraint(
            constraint_id=uid(number), kind=kind, left=uid(left),
            right=uid(right), provenance=provenance,
        )
        for number, kind, left, right in (
            (30, "requires", 2, 3), (31, "excludes", 3, 4),
        )
    ) if constrained else ()
    observations = tuple(
        ProductObservation(
            observation_id=identity, product_id=uid(300 + index),
            product_revision=1, observed_at=STAMP,
            present=tuple(map(uid, selected)),
            absent=tuple(uid(number) for number in FEATURES if number not in selected),
            complete=True, provenance=provenance,
        )
        for index, (selected, identity) in enumerate(OBSERVATIONS.items())
    )
    return FeatureGraphRevision(
        graph_id=uid(10), revision=1, valid_from=STAMP, recorded_at=STAMP,
        features=definitions, constraints=constraints, observations=observations,
    )


class FeatureGraphExactCountTests(unittest.TestCase):
    def enumerate_fixture(self, snapshot):
        service, repository = build_memory_feature_graph()
        service.append(snapshot, expected_revision=0)
        before = snapshot.model_dump_json()
        history = repository.history(snapshot.graph_id)
        receipts = {}
        for bits in product((False, True), repeat=len(FEATURES)):
            selected = tuple(number for number, enabled in zip(FEATURES, bits) if enabled)
            request = ConfigurationRequest(
                configuration_id=uid(1000 + sum(1 << (number - 1) for number in selected)),
                graph_id=snapshot.graph_id, graph_revision=snapshot.revision,
                graph_digest=snapshot.digest(), selected=tuple(map(uid, selected)),
            )
            result = service.validate(request)
            with self.subTest(selected=selected):
                self.assertIs(result.candidate_only, True)
                self.assertEqual(result.configuration_id, request.configuration_id)
                self.assertEqual(result.graph_id, snapshot.graph_id)
                self.assertEqual(result.graph_revision, snapshot.revision)
                self.assertEqual(result.graph_digest, snapshot.digest())
                self.assertEqual(result.request_digest, request.digest())
            receipts[selected] = result
        self.assertEqual(len(receipts), 16)
        self.assertEqual(snapshot.model_dump_json(), before)
        self.assertEqual(repository.history(snapshot.graph_id), history)
        self.assertEqual(len(repository.history(snapshot.graph_id)), 1)
        return receipts

    def test_exact_count_and_allowed_set_match_hand_enumerated_fixture(self):
        receipts = self.enumerate_fixture(exact_count_fixture())
        allowed = frozenset(selected for selected, result in receipts.items()
                            if result.model_outcome == "allowed_by_model")
        self.assertEqual(allowed, EXPECTED_ALLOWED)
        self.assertEqual(len(allowed), 4)
        for selected, result in receipts.items():
            with self.subTest(selected=selected):
                permitted = selected in EXPECTED_ALLOWED
                observed = selected in OBSERVATIONS
                self.assertEqual(result.model_outcome,
                                 "allowed_by_model" if permitted else "violates_model")
                self.assertEqual(result.violations == (), permitted)
                self.assertEqual(result.observation_ids,
                                 (OBSERVATIONS[selected],) if observed else ())
                self.assertEqual(result.evidence_status,
                                 "observed_configuration" if observed else
                                 ("possible" if permitted else "not_model_permitted"))

    def test_free_and_mandatory_only_exact_count_controls(self):
        for mandatory, expected_count in ((False, 16), (True, 8)):
            with self.subTest(mandatory=mandatory):
                receipts = self.enumerate_fixture(
                    exact_count_fixture(mandatory=mandatory, constrained=False))
                expected = frozenset(
                    selected for selected in receipts if not mandatory or 1 in selected)
                actual = frozenset(selected for selected, result in receipts.items()
                                   if result.model_outcome == "allowed_by_model")
                self.assertEqual(actual, expected)
                self.assertEqual(len(actual), expected_count)

    def test_candidate_only_cannot_be_disabled_in_any_result_state(self):
        receipts = self.enumerate_fixture(exact_count_fixture())
        # possible, observed/allowed, observed/violating, unobserved/violating.
        for selected in ((1,), (1, 3), (1, 2), ()):
            with self.subTest(selected=selected):
                result = receipts[selected]
                restored = ConfigurationResult.model_validate_json(result.model_dump_json())
                self.assertEqual(restored, result)
                self.assertIs(restored.candidate_only, True)
                with self.assertRaises(ValidationError):
                    ConfigurationResult.model_validate(result.model_dump() | {"candidate_only": False})
                for field in ("approved", "ordered", "installed", "test_passed", "grants_authority"):
                    self.assertNotIn(field, result.model_dump())


if __name__ == "__main__":
    unittest.main()
