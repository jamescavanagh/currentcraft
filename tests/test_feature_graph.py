"""Synthetic evidence only: no external data, network, service stubs or private mappings."""
from datetime import datetime, timedelta, timezone
import unittest
from uuid import UUID

from pydantic import ValidationError
from app.application.feature_graph import AsOfRequest, ConfigurationRequest, compare_snapshots
from app.domain.operand.feature_graph import FeatureConstraint, FeatureDefinition, FeatureGraphRevision, ProductObservation, Provenance
from app.infrastructure.feature_graph import build_memory_feature_graph


def uid(number):
    return UUID(int=number)


def at(day):
    return datetime(2020, 1, day, tzinfo=timezone.utc)


def evidence(number=100, day=1):
    return Provenance(evidence_id=uid(number), source_snapshot_id=uid(number + 1000), captured_at=at(day), method="human_label")


def feature(number, version=1, status="active", mandatory=False):
    return FeatureDefinition(feature_id=uid(number), version=version, definition_digest=f"{number:064x}",
        status=status, mandatory=mandatory, provenance=evidence())


def observation(present=(1,), complete=True, absent=()):
    return ProductObservation(observation_id=uid(200), product_id=uid(300), product_revision=1,
        observed_at=at(1), present=tuple(map(uid, present)), absent=tuple(map(uid, absent)),
        complete=complete, provenance=evidence())


def graph(revision=1, features=None, **kwargs):
    return FeatureGraphRevision(graph_id=uid(10), revision=revision, valid_from=at(revision), recorded_at=at(revision),
        features=tuple(features if features is not None else (feature(1), feature(2))), **kwargs)


def request(snapshot, selected=(1,)):
    return ConfigurationRequest(configuration_id=uid(20), graph_id=snapshot.graph_id, graph_revision=snapshot.revision,
        graph_digest=snapshot.digest(), selected=tuple(map(uid, selected)))


class FeatureGraphTests(unittest.TestCase):
    def setUp(self):
        self.service, self.repository = build_memory_feature_graph()

    def add(self, snapshot):
        self.service.append(snapshot, expected_revision=snapshot.revision - 1)
        return snapshot

    def test_introduce_carry_retire_and_reconstruct_three_revisions(self):
        first = self.add(graph(1, (feature(1),)))
        second = self.add(graph(2, (feature(1), feature(2))))
        third = self.add(graph(3, (feature(1), feature(2, version=2, status="retired"))))
        self.assertEqual(compare_snapshots(first, second).introduced, (uid(2),))
        self.assertEqual(compare_snapshots(second, third).carried, (uid(1),))
        self.assertEqual(compare_snapshots(second, third).retired, (uid(2),))
        for snapshot in (first, second, third):
            result = self.service.as_of(AsOfRequest(graph_id=uid(10), effective_at=snapshot.valid_from, known_at=at(4)))
            self.assertEqual(result, snapshot)

    def test_knowledge_cutoff_prevents_future_evidence(self):
        first = self.add(graph())
        second = graph(2).model_dump()
        second["recorded_at"] = at(4)
        self.add(FeatureGraphRevision(**second))
        self.assertEqual(self.service.as_of(AsOfRequest(graph_id=uid(10), effective_at=at(3), known_at=at(3))), first)
        self.assertEqual(self.service.as_of(AsOfRequest(graph_id=uid(10), effective_at=at(3), known_at=at(4))).revision, 2)

    def test_no_snapshot_before_effective_or_knowledge_time(self):
        self.add(graph())
        for effective, known in ((at(1) - timedelta(days=1), at(2)), (at(2), at(1) - timedelta(days=1))):
            self.assertIsNone(self.service.as_of(AsOfRequest(graph_id=uid(10), effective_at=effective, known_at=known)))

    def test_backdated_correction_is_visible_only_after_recording(self):
        self.add(graph())
        correction = graph(2).model_dump()
        correction.update(valid_from=at(1), recorded_at=at(3))
        self.add(FeatureGraphRevision(**correction))
        self.assertEqual(self.service.as_of(AsOfRequest(graph_id=uid(10), effective_at=at(1), known_at=at(2))).revision, 1)
        self.assertEqual(self.service.as_of(AsOfRequest(graph_id=uid(10), effective_at=at(1), known_at=at(3))).revision, 2)

    def test_allowed_unobserved_is_only_possible(self):
        snapshot = self.add(graph(observations=(observation((1,)),)))
        result = self.service.validate(request(snapshot, (1, 2)))
        self.assertEqual((result.model_outcome, result.evidence_status), ("allowed_by_model", "possible"))
        self.assertEqual(result.observation_ids, ())
        self.assertTrue(result.candidate_only)

    def test_complete_exact_observation_is_reported(self):
        snapshot = self.add(graph(observations=(observation(),)))
        result = self.service.validate(request(snapshot))
        self.assertEqual(result.evidence_status, "observed_configuration")
        self.assertEqual(result.observation_ids, (uid(200),))

    def test_partial_observation_does_not_prove_exact_configuration(self):
        snapshot = self.add(graph(observations=(observation(complete=False),)))
        self.assertEqual(self.service.validate(request(snapshot)).evidence_status, "possible")

    def test_model_invalid_observation_is_not_erased(self):
        constraint = FeatureConstraint(constraint_id=uid(30), kind="requires", left=uid(1), right=uid(2), provenance=evidence())
        snapshot = self.add(graph(constraints=(constraint,), observations=(observation(),)))
        result = self.service.validate(request(snapshot))
        self.assertEqual(result.model_outcome, "violates_model")
        self.assertEqual(result.observation_ids, (uid(200),))
        self.assertTrue(result.violations[0].startswith("requires:"))

    def test_excludes_and_mandatory_are_checked(self):
        constraint = FeatureConstraint(constraint_id=uid(30), kind="excludes", left=uid(1), right=uid(2), provenance=evidence())
        snapshot = self.add(graph(features=(feature(1, mandatory=True), feature(2)), constraints=(constraint,)))
        self.assertTrue(self.service.validate(request(snapshot, (1, 2))).violations[0].startswith("excludes:"))
        self.assertTrue(self.service.validate(request(snapshot, ())).violations[0].startswith("mandatory:"))

    def test_unknown_and_retired_selections_fail(self):
        snapshot = self.add(graph(features=(feature(1), feature(2, status="retired"))))
        for selected, prefix in (((99,), "unknown:"), ((2,), "retired:")):
            self.assertTrue(self.service.validate(request(snapshot, selected)).violations[0].startswith(prefix))

    def test_model_identity_revision_and_digest_are_pinned(self):
        snapshot = self.add(graph())
        for key, value in (("graph_id", uid(99)), ("graph_revision", 2), ("graph_digest", "0" * 64)):
            data = request(snapshot).model_dump()
            data[key] = value
            with self.subTest(key=key), self.assertRaises(ValueError):
                self.service.validate(ConfigurationRequest(**data))

    def test_canonical_order_preserves_digest_and_ids(self):
        left = graph(features=(feature(2), feature(1)))
        right = graph(features=(feature(1), feature(2)))
        self.assertEqual(left.digest(), right.digest())
        self.assertEqual(tuple(f.feature_id for f in left.features), (uid(1), uid(2)))
        self.assertEqual(request(left, (2, 1)).digest(), request(right, (1, 2)).digest())

    def test_json_round_trip_preserves_snapshot_identity(self):
        snapshot = graph()
        restored = FeatureGraphRevision.model_validate_json(snapshot.model_dump_json())
        self.assertEqual((restored.graph_id, restored.digest()), (snapshot.graph_id, snapshot.digest()))

    def test_duplicate_feature_observation_constraint_and_selection_rejected(self):
        constraint = FeatureConstraint(constraint_id=uid(30), kind="requires", left=uid(1), right=uid(2), provenance=evidence())
        for kwargs in ({"features": (feature(1), feature(1))}, {"observations": (observation(), observation())},
                       {"constraints": (constraint, constraint)}):
            with self.subTest(kwargs=tuple(kwargs)), self.assertRaises(ValidationError):
                graph(**kwargs)
        with self.assertRaises(ValidationError):
            request(graph(), (1, 1))

    def test_dangling_self_and_retired_constraints_rejected(self):
        for left, right in ((1, 1), (1, 99), (1, 2)):
            with self.subTest(right=right), self.assertRaises(ValidationError):
                constraint = FeatureConstraint(constraint_id=uid(30), kind="requires", left=uid(left), right=uid(right), provenance=evidence())
                graph(features=(feature(1), feature(2, status="retired")), constraints=(constraint,))

    def test_observation_unknown_absent_and_conflict(self):
        partial = observation(present=(1,), complete=False)
        self.assertNotIn(uid(2), partial.absent)
        self.assertNotIn(uid(2), partial.present)
        self.assertEqual(observation(present=(1,), absent=(2,)).absent, (uid(2),))
        with self.assertRaises(ValidationError):
            observation(present=(1,), absent=(1,))
        with self.assertRaises(ValidationError):
            graph(observations=(observation(present=(99,)),))

    def test_timezone_and_future_evidence_guards(self):
        data = graph().model_dump()
        for key, value in (("valid_from", datetime(2020, 1, 1)), ("valid_from", at(2))):
            with self.subTest(key=key), self.assertRaises(ValidationError):
                FeatureGraphRevision(**(data | {key: value}))
        bad = feature(1).model_dump()
        bad["provenance"] = evidence(day=2)
        with self.assertRaises(ValidationError):
            graph(features=(FeatureDefinition(**bad),))
        with self.assertRaises(ValidationError):
            AsOfRequest(graph_id=uid(10), effective_at=datetime(2020, 1, 1), known_at=at(2))

    def test_equivalent_timezones_have_identical_digest(self):
        data = graph().model_dump()
        data["valid_from"] = data["valid_from"].astimezone(timezone(timedelta(hours=-8)))
        self.assertEqual(FeatureGraphRevision(**data).digest(), graph().digest())

    def test_append_is_idempotent_and_cas_protected(self):
        first = self.add(graph())
        self.service.append(first, expected_revision=0)
        self.assertEqual(len(self.repository.history(uid(10))), 1)
        with self.assertRaises(ValueError):
            self.service.append(graph(2), expected_revision=0)
        with self.assertRaises(ValueError):
            self.service.append(graph(3), expected_revision=1)
        with self.assertRaises(ValueError):
            self.service.append(graph(features=(feature(2),)), expected_revision=0)

    def test_definition_mutation_and_regression_rejected(self):
        self.add(graph(features=(feature(1),)))
        with self.assertRaises(ValueError):
            self.add(graph(2, (feature(1, status="retired"),)))
        self.add(graph(2, (feature(1, version=2),)))
        with self.assertRaises(ValueError):
            self.add(graph(3, (feature(1),)))

    def test_recorded_time_cannot_regress(self):
        data = graph().model_dump()
        data["recorded_at"] = at(4)
        self.add(FeatureGraphRevision(**data))
        with self.assertRaises(ValueError):
            self.add(graph(2))

    def test_disappearance_is_not_retirement(self):
        first = graph()
        second = graph(2, (feature(1),))
        diff = compare_snapshots(first, second)
        self.assertEqual(diff.no_longer_listed, (uid(2),))
        self.assertEqual(diff.retired, ())

    def test_changed_definition_is_not_unchanged_carriage(self):
        diff = compare_snapshots(graph(), graph(2, (feature(1, version=2), feature(2))))
        self.assertEqual(diff.changed, (uid(1),))
        self.assertEqual(diff.carried, (uid(2),))

    def test_comparison_rejects_reversed_or_foreign_graph(self):
        with self.assertRaises(ValueError):
            compare_snapshots(graph(2), graph())
        foreign = graph(2).model_dump() | {"graph_id": uid(99)}
        with self.assertRaises(ValueError):
            compare_snapshots(graph(), FeatureGraphRevision(**foreign))

    def test_no_operational_authority_or_private_fields(self):
        snapshot = self.add(graph())
        result = self.service.validate(request(snapshot))
        for field in ("ordered", "installed", "test_passed", "approved", "source_locator", "part_number"):
            self.assertNotIn(field, result.model_dump())
        with self.assertRaises(ValidationError):
            FeatureGraphRevision(**(snapshot.model_dump() | {"approved": True}))
        with self.assertRaises(ValidationError):
            snapshot.revision = 2


if __name__ == "__main__":
    unittest.main()
