"""Synthetic model/evidence tests; no raw files, resolver or live service."""
from datetime import datetime, timezone
import importlib.util
from pathlib import Path
import unittest

from pydantic import ValidationError
from app.application.models import (
    CONTRACTS, ConfigurationArtifactRevision as Artifact, DatasetManifest as Dataset,
    SanitizationAssessment as Assessment, check_dataset_artifacts,
    check_assessment_artifacts, check_phase_assessment,
)
from app.application.phase.contracts import PhaseReading, PhaseRevision

T = datetime(2026, 1, 1, tzinfo=timezone.utc)
D = "0" * 64
E = "1" * 64


def artifact(**updates):
    args = dict(artifact_id="artifact-a", revision_id="r1", content_digest=D,
                payload_ref="payload-a", product_instance_id="instance-a",
                applicability_profile_ref="profile-a@r1", source_id="source-a",
                source_version="r1", captured_at=T, capture_method="capture/1")
    args.update(updates)
    return Artifact(**args)


def dataset(**updates):
    args = dict(manifest_id="dataset-a", revision_id="r1", input_refs=("artifact-a@r1",),
                input_digests=(D,), mapping_digest=D, config_digest=D, method="build/1",
                split_policy_ref="split-a@r1", split_assignments=(("artifact-a@r1", "test"),),
                feature_spec_ref="features-a@r1", label_spec_ref="labels-a@r1",
                run_ref="build-a", created_at=T)
    args.update(updates)
    return Dataset(**args)


def assessment(**updates):
    args = dict(assessment_id="assessment-a", revision_id="r1",
                input_ref="artifact-a@r1", input_digest=D,
                output_ref="artifact-b@r1", output_digest=E,
                tool_version="tool/1", rules_version="rules/1", mapping_digest=D,
                config_digest=D, method="assessment/1", coverage_profile_ref="coverage-a@r1",
                required_surfaces=("body",), inspected_surfaces=("body",),
                findings_ref="findings-a", outcome="processed", run_ref="assessment-run", assessed_at=T)
    args.update(updates)
    return Assessment(**args)


def phase():
    return PhaseRevision(phase_id="phase-a", revision_id="r1", subsystem_id="subsystem-a",
                         ordinal=1, entry_profile_version="entry/1")


def reading(**updates):
    args = dict(reading_id="reading-a", phase_ref=phase().ref, kind="measurement",
                source_id="assessment-a", source_version="r1", mapping_digest=D,
                config_digest=D, method="reading-production/2", validity="unknown",
                run_ref="reading-run", observed_at=T)
    args.update(updates)
    return PhaseReading(**args)


class ModelsEvidence(unittest.TestCase):
    def test_valid_artifact(self):
        self.assertEqual(artifact().ref, "artifact-a@r1")

    def test_unknown_source_explicit(self):
        self.assertIsNone(artifact(source_version=None, source_version_unknown_reason="not_exposed").source_version)

    def test_unknown_source_requires_reason(self):
        with self.assertRaises(ValidationError):
            artifact(source_version=None)

    def test_known_source_rejects_unknown_reason(self):
        with self.assertRaises(ValidationError):
            artifact(source_version_unknown_reason="unavailable")

    def test_unknown_reason_controlled(self):
        with self.assertRaises(ValidationError):
            artifact(source_version=None, source_version_unknown_reason="arbitrary")

    def test_naive_times_rejected(self):
        for factory, field in ((artifact, "captured_at"), (dataset, "created_at"), (assessment, "assessed_at")):
            with self.subTest(field=field), self.assertRaises(ValidationError):
                factory(**{field: datetime(2026, 1, 1)})

    def test_frozen_closed_synthetic(self):
        for factory in (artifact, dataset, assessment):
            with self.subTest(factory=factory.__name__):
                value = factory()
                with self.assertRaises(ValidationError):
                    value.epistemic_status = "synthetic"
                with self.assertRaises(ValidationError):
                    factory(extra_field=True)
                with self.assertRaises(ValidationError):
                    factory(epistemic_status="production")

    def test_opaque_payload_ref(self):
        with self.assertRaises(ValidationError):
            artifact(payload_ref="https://example.invalid/payload")

    def test_digest_format(self):
        with self.assertRaises(ValidationError):
            artifact(content_digest="not-a-digest")

    def test_fingerprints_roundtrip(self):
        for factory in (artifact, dataset, assessment):
            value = factory()
            clone = type(value).model_validate_json(value.model_dump_json())
            self.assertEqual(value.fingerprint(), clone.fingerprint())

    def test_behavior_fields_change_fingerprint(self):
        original = assessment()
        changes = dict(tool_version="tool/2", rules_version="rules/2", mapping_digest=E,
                       config_digest=E, method="assessment/2", coverage_profile_ref="coverage-a@r2",
                       findings_ref="findings-b", run_ref="run-b", output_digest=D)
        for key, value in changes.items():
            with self.subTest(field=key):
                self.assertNotEqual(original.fingerprint(), assessment(**{key: value}).fingerprint())

    def test_dataset_duplicates(self):
        with self.assertRaises(ValidationError):
            dataset(input_refs=("artifact-a@r1", "artifact-a@r1"), input_digests=(D, D),
                    split_assignments=(("artifact-a@r1", "train"), ("artifact-a@r1", "test")))

    def test_dataset_missing_digest(self):
        with self.assertRaises(ValidationError):
            dataset(input_digests=(D, E))

    def test_dataset_missing_split(self):
        with self.assertRaises(ValidationError):
            dataset(split_assignments=())

    def test_dataset_foreign_split(self):
        with self.assertRaises(ValidationError):
            dataset(split_assignments=(("artifact-b@r1", "test"),))

    def test_same_feature_label_spec_rejected(self):
        with self.assertRaises(ValidationError):
            dataset(label_spec_ref="features-a@r1")

    def test_dataset_exact_records(self):
        check_dataset_artifacts(dataset(), (artifact(),))

    def test_dataset_wrong_digest_or_missing(self):
        for records in ((), (artifact(content_digest=E),)):
            with self.assertRaises(ValueError):
                check_dataset_artifacts(dataset(), records)

    def test_duplicate_supplied_revision(self):
        with self.assertRaises(ValueError):
            check_dataset_artifacts(dataset(), (artifact(), artifact()))

    def test_wrong_artifact_type(self):
        with self.assertRaises(ValueError):
            check_dataset_artifacts(dataset(), (assessment(),))

    def test_assessment_exact_records(self):
        check_assessment_artifacts(assessment(), (artifact(), artifact(artifact_id="artifact-b", content_digest=E)))

    def test_assessment_output_mismatch(self):
        with self.assertRaises(ValueError):
            check_assessment_artifacts(assessment(), (artifact(), artifact(artifact_id="artifact-b")))

    def test_unpaired_output(self):
        for changes in ({"output_ref": None}, {"output_digest": None}):
            with self.assertRaises(ValidationError):
                assessment(**changes)

    def test_processed_requires_output(self):
        with self.assertRaises(ValidationError):
            assessment(output_ref=None, output_digest=None)

    def test_processed_rejects_unresolved(self):
        with self.assertRaises(ValidationError):
            assessment(unresolved_surfaces=("comments",))

    def test_missing_surface_explicit(self):
        with self.assertRaises(ValidationError):
            assessment(outcome="review_required", inspected_surfaces=(), limitation_codes=("coverage_missing",))

    def test_review_with_missing_surface(self):
        value = assessment(outcome="review_required", inspected_surfaces=(), unresolved_surfaces=("body",),
                           limitation_codes=("coverage_missing",))
        self.assertEqual(value.outcome, "review_required")

    def test_blocked_has_no_usable_output(self):
        with self.assertRaises(ValidationError):
            assessment(outcome="blocked", limitation_codes=("unsupported_format",))
        value = assessment(outcome="blocked", output_ref=None, output_digest=None,
                           limitation_codes=("unsupported_format",))
        self.assertIsNone(value.output_ref)

    def test_nonprocessed_requires_reason(self):
        with self.assertRaises(ValidationError):
            assessment(outcome="review_required")

    def test_duplicate_surfaces(self):
        with self.assertRaises(ValidationError):
            assessment(inspected_surfaces=("body", "body"))

    def test_link_valid_unknown_not_promoted(self):
        value = reading()
        before = value.model_dump_json()
        check_phase_assessment(value, assessment(), phase())
        self.assertEqual(value.validity, "unknown")
        self.assertEqual(value.model_dump_json(), before)

    def test_link_methods_runs_times_distinct(self):
        check_phase_assessment(reading(observed_at=datetime(2026, 1, 2, tzinfo=timezone.utc)),
                               assessment(), phase())

    def test_link_wrong_source_revision_phase_or_digest(self):
        for changes in ({"source_id": "other"}, {"source_version": "r2"}, {"phase_ref": "phase-a@r2"},
                        {"mapping_digest": E}, {"config_digest": E}):
            with self.subTest(changes=tuple(changes)), self.assertRaises(ValueError):
                check_phase_assessment(reading(**changes), assessment(), phase())

    def test_link_wrong_record_type(self):
        with self.assertRaises(ValueError):
            check_phase_assessment(reading(), artifact(), phase())

    def test_reference_and_existing_input_unchanged(self):
        value = artifact()
        before = value.model_dump_json()
        check_dataset_artifacts(dataset(), (value,))
        self.assertEqual(value.ref, "artifact-a@r1")
        self.assertEqual(value.model_dump_json(), before)

    def test_descriptions_present(self):
        for model in CONTRACTS:
            for name, field in model.model_fields.items():
                self.assertTrue(field.description, (model.__name__, name))

    def test_generated_reference_drift(self):
        root = Path(__file__).resolve().parents[1]
        path = root / "scripts/gen_models_contract_docs.py"
        spec = importlib.util.spec_from_file_location("models_docs", path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        expected = module.render()
        for rel, text in expected.items():
            self.assertEqual((root / "docs/contracts" / rel).read_text(), text, rel)
        actual = {str(p.relative_to(root / "docs/contracts"))
                  for p in (root / "docs/contracts/schemas/models").glob("*.json")}
        self.assertEqual(actual, {r for r in expected if r.endswith(".json")})


if __name__ == "__main__":
    unittest.main()
