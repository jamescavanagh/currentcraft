"""Canonical reference resolution for six-type extensions, under a synthetic referenced standard.

Ownership rules come from the ownership profile pinned to the domain's framework profile (synthetic
SYN-A here). Real profiles are private REF data; nothing here represents an adopted standard.
"""
import hashlib
import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from pydantic import ValidationError
from app.application.feature_graph.domain_types import resolve_six_type_packet
from app.application.feature_graph.references import CanonicalLookup, OwnershipProfile, resolve_extensions
from app.domain.commercial.commercial_order import Order
from app.domain.document.document import Document
from app.domain.document.revision import Revision
from app.domain.product.asset_instance import AssetInstance
from app.domain.project.project_entity import Project
from app.domain.project.subsystem import Subsystem
from app.domain.project.wbs import WBS
from app.domain.quality.quality_evidence import QualityEvidence
from app.infrastructure.feature_graph.canonical import CanonicalSnapshotPort
from app.infrastructure.feature_graph.ownership import check_standard_binding, load_ownership_profile
from tests.test_six_domain_types import MOMENT, cref, fact, fixture, rebuild, uid

ROOT = Path(__file__).resolve().parent.parent
FIXTURES = ROOT / "tests/fixtures/framework_profiles"
OWNERSHIP = json.loads((FIXTURES / "synthetic_ownership.json").read_text())
FRAMEWORK = json.loads((FIXTURES / "synthetic_profiles.json").read_text())["profiles"][0]
AT = datetime(2026, 6, 1, tzinfo=timezone.utc)


def profile(**changes):
    return OwnershipProfile.model_validate(OWNERSHIP | changes)


def canonical_records(**overrides):
    p = uid(100)
    records = {
        "project": Project(entity_id=p, record_version=2),
        "document": Document(entity_id=uid(102), project_id=p),
        "revision": Revision(entity_id=uid(202), record_version=7, project_id=p, document_id=uid(102)),
        "spec": Revision(entity_id=uid(406), project_id=p, document_id=uid(102)),
        "order": Order(entity_id=uid(103), project_id=p),
        "subsystem": Subsystem(entity_id=uid(104), project_id=p),
        "wbs": WBS(entity_id=uid(700), project_id=p),
        "component": AssetInstance(entity_id=uid(404), project_id=p, product_definition_id=uid(410)),
        "peer": AssetInstance(entity_id=uid(405), project_id=p, product_definition_id=uid(410)),
        "evidence": QualityEvidence(entity_id=uid(900), source="synthetic", source_version="1",
                                    locator="synthetic://evidence", status="observed", recorded_at=MOMENT),
    }
    records.update(overrides)
    return tuple(r for r in records.values() if r is not None)


def findings(report, role):
    return next(f.findings for f in report.references if f.role == role)


class OwnershipProfileTests(unittest.TestCase):
    def test_synthetic_profile_is_drawn_from_the_referenced_standard(self):
        check_standard_binding(profile(), FRAMEWORK)
        self.assertTrue(OWNERSHIP["standard"]["framework_id"].startswith("SYN-"))

    def test_binding_fails_for_another_edition_or_foreign_concept(self):
        with self.assertRaisesRegex(ValueError, "not pinned"):
            check_standard_binding(profile(), FRAMEWORK | {"framework_edition": "synthetic-2"})
        rules = [dict(OWNERSHIP["rules"][0], concept_id="SYN-A.C9")] + OWNERSHIP["rules"][1:]
        with self.assertRaisesRegex(ValueError, "outside the referenced standard"):
            check_standard_binding(profile(rules=rules), FRAMEWORK)
        rules = [dict(OWNERSHIP["rules"][0], concept_id="SYN-A.C3")] + OWNERSHIP["rules"][1:]
        with self.assertRaisesRegex(ValueError, "does not map"):
            check_standard_binding(profile(rules=rules), FRAMEWORK)

    def test_profile_is_closed(self):
        bad_rule = dict(OWNERSHIP["rules"][0], via="title")
        for changes in ({"rules": [bad_rule]}, {"roots": ["project", "document"]},
                        {"rules": OWNERSHIP["rules"] + [dict(OWNERSHIP["rules"][0], rule_id="X")]},
                        {"valid_from": "2026-01-01T00:00:00"}, {"extra": True}):
            with self.subTest(changes=list(changes)), self.assertRaises(ValidationError):
                profile(**changes)

    def test_loader_pins_bytes_path_and_validity(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "private"
            (root / "ref").mkdir(parents=True)
            raw = (FIXTURES / "synthetic_ownership.json").read_bytes()
            (root / "ref/ownership.json").write_bytes(raw)
            digest = hashlib.sha256(raw).hexdigest()
            loaded = load_ownership_profile(root, "ref/ownership.json", digest, AT)
            self.assertEqual(loaded, profile())
            for args, message in (((root, "ref/ownership.json", "0" * 64, AT), "SHA-256"),
                                  ((root, "../ownership.json", digest, AT), "inside the REF root"),
                                  ((root, "ref/ownership.json", digest, datetime(2025, 1, 1, tzinfo=timezone.utc)), "not valid")):
                with self.subTest(message), self.assertRaisesRegex(ValueError, message):
                    load_ownership_profile(*args)
            (root / "ref/dup.json").write_text('{"schema": "framework-ownership/0", "schema": "x"}')
            with self.assertRaisesRegex(ValueError, "duplicate"):
                load_ownership_profile(root, "ref/dup.json", hashlib.sha256((root / "ref/dup.json").read_bytes()).hexdigest(), AT)
            with self.assertRaisesRegex(ValueError, "absolute"):
                load_ownership_profile(Path("private"), "ref/ownership.json", digest, AT)


class ReferenceResolutionTests(unittest.TestCase):
    def setUp(self):
        self.packet = fixture()
        self.profile = profile()

    def resolve(self, records=None, packet=None, **kwargs):
        port = CanonicalSnapshotPort(records if records is not None else canonical_records(), **kwargs)
        return resolve_six_type_packet(packet or self.packet, port, self.profile, AT)

    def test_consistent_packet_is_canonically_verified(self):
        report = self.resolve()
        self.assertEqual(report.outcome, "canonically_verified", [f for f in report.references if f.findings != ("verified",)])
        self.assertEqual(report.standard.framework_id, "SYN-A")
        self.assertFalse(report.grants_authority)
        self.assertTrue(all(f.record_digest for f in report.references))
        self.assertIn("SYN-A.O2", next(f.rules_applied for f in report.references if f.role == "captured_revision"))

    def test_wrong_kind_is_blocked_even_when_identity_and_version_exist(self):
        records = canonical_records(component=Project(entity_id=uid(404)))
        report = self.resolve(records)
        self.assertEqual(report.outcome, "blocked")
        self.assertIn("kind_mismatch", findings(report, "components[0]"))

    def test_exact_version_is_required(self):
        records = canonical_records(revision=Revision(entity_id=uid(202), record_version=6, project_id=uid(100), document_id=uid(102)))
        report = self.resolve(records)
        self.assertEqual(report.outcome, "blocked")
        self.assertEqual(findings(report, "captured_revision"), ("version_absent",))

    def test_project_ownership_mismatch_blocks(self):
        records = canonical_records(order=Order(entity_id=uid(103), project_id=uid(199)))
        report = self.resolve(records)
        self.assertEqual(report.outcome, "blocked")
        self.assertEqual(findings(report, "order"), ("project_owner_mismatch",))

    def test_revision_of_another_document_is_blocked(self):
        records = canonical_records(revision=Revision(entity_id=uid(202), record_version=7, project_id=uid(100), document_id=uid(150)))
        report = self.resolve(records)
        self.assertEqual(report.outcome, "blocked")
        self.assertEqual(findings(report, "captured_revision"), ("owner_mismatch",))

    def test_derived_revision_may_belong_to_another_document(self):
        other = Revision(entity_id=uid(250), project_id=uid(100), document_id=uid(150))
        document = rebuild(self.packet.document, derived_from=(cref("revision", 250),))
        report = self.resolve(canonical_records(other=other), rebuild(self.packet, document=document))
        self.assertEqual(findings(report, "derived_from[0]"), ("verified",))

    def test_unknown_owner_leaves_reference_unverified_not_verified(self):
        report_profile = profile(rules=[r for r in OWNERSHIP["rules"] if r["rule_id"] != "SYN-A.O5"]
                                 + [dict(OWNERSHIP["rules"][4], required=True)])
        port = CanonicalSnapshotPort(canonical_records())
        report = resolve_six_type_packet(self.packet, port, report_profile, AT)
        self.assertEqual(report.outcome, "unverified")
        self.assertEqual(findings(report, "subsystem"), ("owner_unknown",))

    def test_kind_without_a_rule_in_the_standard_is_unverified(self):
        trimmed = profile(rules=[r for r in OWNERSHIP["rules"] if r["subject_kind"] != "wbs"])
        report = resolve_six_type_packet(self.packet, CanonicalSnapshotPort(canonical_records()), trimmed, AT)
        self.assertEqual(report.outcome, "unverified")
        self.assertEqual(findings(report, "work_packages[0]"), ("ownership_rule_absent",))

    def test_missing_required_blocks_but_missing_optional_stays_candidate(self):
        report = self.resolve(canonical_records(document=None))
        self.assertEqual(findings(report, "document"), ("required_not_found",))
        self.assertEqual(report.outcome, "blocked")
        project = rebuild(self.packet.project, phase=fact(cref("phase", 710)))
        report = self.resolve(packet=rebuild(self.packet, project=project))
        self.assertEqual(findings(report, "phase"), ("unresolved_candidate",))
        self.assertEqual(report.outcome, "unverified")

    def test_access_denied_is_reported_and_blocks(self):
        report = self.resolve(denied=(uid(103),))
        self.assertEqual(findings(report, "order"), ("access_denied",))
        self.assertEqual(report.outcome, "blocked")

    def test_port_refuses_extensions_as_canonical_records(self):
        with self.assertRaises(TypeError):
            CanonicalSnapshotPort(canonical_records() + (self.packet.document,))

    def test_profile_must_be_valid_at_resolution_time(self):
        with self.assertRaisesRegex(ValueError, "not valid"):
            resolve_extensions(self.packet.extensions(), CanonicalSnapshotPort(canonical_records()), self.profile,
                               datetime(2025, 1, 1, tzinfo=timezone.utc))

    def test_forged_lookup_shapes_are_rejected(self):
        with self.assertRaises(ValidationError):
            CanonicalLookup(status="found")
        with self.assertRaises(ValidationError):
            CanonicalLookup(status="not_found", kind="order")

    def test_report_carries_codes_not_source_text(self):
        text = self.resolve().model_dump_json()
        for value in ("synthetic scope", "synthetic boundary", "synthetic://evidence", "synthetic conditions"):
            self.assertNotIn(value, text)


if __name__ == "__main__":
    unittest.main()
