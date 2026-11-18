"""Review D04/D05/D08, provenance support, selection trust and historical capture."""
import copy
from datetime import timedelta
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from pydantic import ValidationError

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
from app.application.enterprise.contracts import EnterpriseSnapshot
from app.application.enterprise.services import (ReferenceError, PolicyNotDefined, hydrate_snapshot,
    capture_snapshot, restore_snapshot, request_consultant_transition, payload_digest)
from app.application.persistence.contracts import VersionedRecord
from app.infrastructure.enterprise.wiring import (AT, FIXTURE_REFERENCE_PATH,
    FIXTURE_REFERENCE_SHA256, fixture_id, build_fixture_with_selection)
from app.infrastructure.enterprise.references import load_references
from app.infrastructure.persistence.memory import MemoryStore
from tests.integration.test_enterprise import optional_data, fact


class ReviewCorrections(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        inputs = build_fixture_with_selection(ROOT / "references")
        cls.snapshot, cls.selection = inputs.snapshot, inputs.selection

    def raw(self):
        return self.snapshot.model_dump(mode="json")

    def optional(self):
        return optional_data(self.snapshot)

    def find(self, raw, kind):
        return next(r for r in raw["records"] if r["kind"] == kind)

    def evidence(self, raw, number, status="observed", inputs=None):
        evidence = copy.deepcopy(raw["records"][0])
        evidence.update(entity_id=str(fixture_id(number)), status=status, locator=f"synthetic://assertion/{number}")
        evidence["derivation"] = None if status != "inferred" else {
            "method_ref": "synthetic://derivation/v1", "input_evidence_ids": [str(fixture_id(i)) for i in inputs]}
        raw["records"].append(evidence)
        return evidence

    def test_d08_known_territory_dates_contacts_and_roundtrip(self):
        raw = self.optional()
        rep = self.find(raw, "manufacturer_rep")
        rep.update(territory=fact("Synthetic territory"),
            agreement_dates={"starts_on": fact("1999-01-01"), "ends_on": fact("2000-12-31")},
            contact_party_ids=fact([str(fixture_id(2))]))
        snapshot = hydrate_snapshot(raw)
        store = MemoryStore()
        capture_snapshot(store, snapshot, selection=self.selection)
        self.assertEqual(restore_snapshot(store, snapshot.snapshot_id), snapshot)

    def test_d08_unknown_bounds_contacts_and_optional_project(self):
        raw = self.optional()
        rep = self.find(raw, "manufacturer_rep")
        rep.pop("project_id")
        rep["agreement_dates"] = {"starts_on": fact("1999-01-01")}
        snapshot = hydrate_snapshot(raw)
        record = next(r for r in snapshot.records if r.kind == "manufacturer_rep")
        self.assertIsNone(record.project_id.value)
        self.assertIsNone(record.contact_party_ids.value)
        self.assertIsNone(record.agreement_dates.ends_on.value)
        self.assertEqual(record.project_id.epistemic_status, "unknown")

    def test_d08_known_date_order_is_enforced(self):
        raw = self.optional()
        self.find(raw, "manufacturer_rep")["agreement_dates"] = {
            "starts_on": fact("2000-01-02"), "ends_on": fact("2000-01-01")}
        with self.assertRaisesRegex(ValidationError, "end precedes start"):
            hydrate_snapshot(raw)

    def test_d08_contacts_and_parties_are_typed_references(self):
        for field, target in (("contact_party_ids", 999), ("contact_party_ids", 3),
                              ("representative_party_id", 3), ("manufacturer_party_id", 999)):
            raw = self.optional()
            rep = self.find(raw, "manufacturer_rep")
            rep[field] = fact([str(fixture_id(target))]) if field == "contact_party_ids" else str(fixture_id(target))
            with self.subTest(field=field, target=target), self.assertRaises(ReferenceError):
                hydrate_snapshot(raw)

    def test_d04_project_and_subsystem_contexts(self):
        raw = self.optional()
        stakeholder = self.find(raw, "stakeholder")
        self.assertEqual(hydrate_snapshot(raw).records[-1].kind, "order")
        stakeholder["context"] = {"kind": "subsystem", "project_id": str(fixture_id(5)), "subsystem_id": str(fixture_id(7))}
        snapshot = hydrate_snapshot(raw)
        relationship = next(r for r in snapshot.records if r.kind == "stakeholder")
        self.assertEqual(relationship.context.kind, "subsystem")
        self.assertFalse(hasattr(relationship, "permits"))
        self.assertNotIn("approval_authority", type(relationship).model_fields)

    def test_d04_context_endpoint_type_and_membership(self):
        for target in (999, 3):
            raw = self.optional()
            self.find(raw, "stakeholder")["context"] = {
                "kind": "subsystem", "project_id": str(fixture_id(5)), "subsystem_id": str(fixture_id(target))}
            with self.subTest(target=target), self.assertRaises(ReferenceError):
                hydrate_snapshot(raw)
        raw = self.optional()
        other = copy.deepcopy(self.find(raw, "project")); other["entity_id"] = str(fixture_id(250)); raw["records"].append(other)
        self.find(raw, "stakeholder")["context"] = {
            "kind": "subsystem", "project_id": str(fixture_id(250)), "subsystem_id": str(fixture_id(7))}
        with self.assertRaisesRegex(ReferenceError, "declared project"):
            hydrate_snapshot(raw)

    def test_d04_undefined_contract_and_decision_contexts_are_blocked(self):
        for kind in ("contract", "decision", "anything"):
            raw = self.optional()
            self.find(raw, "stakeholder")["context"] = {"kind": kind, "target_id": str(fixture_id(5))}
            with self.subTest(kind=kind), self.assertRaises(ValidationError):
                hydrate_snapshot(raw)

    def with_claim(self, party_form="individual", evidence=True, executor=True):
        raw = self.optional()
        person = self.find(raw, "party")
        person["party_form"] = fact("individual")
        engagement = self.find(raw, "consultant")
        if party_form == "firm":
            firm = copy.deepcopy(person)
            firm.update(entity_id=str(fixture_id(251)), name=fact("Synthetic consulting firm"), party_form=fact("firm"))
            raw["records"].append(firm)
            engagement["party_id"] = firm["entity_id"]
        engagement["approval_claim_ids"] = [str(fixture_id(240))]
        claim = {"claim_id": str(fixture_id(240)), "engagement_id": engagement["entity_id"],
            "context": copy.deepcopy(engagement["context"]),
            "authority": {"holder_role": "synthetic.consultant", "scope": "approve_design"}}
        if evidence:
            claim["authority"]["evidence_ref"] = str(fixture_id(1))
            claim["authority_evidence_missing_reason"] = None
        if executor:
            claim["executor_id"] = fact(str(fixture_id(3)))
        raw["approval_claims"] = [claim]
        return raw

    def test_d05_individual_and_firm_claims_roundtrip_as_unverified(self):
        for form in ("individual", "firm"):
            snapshot = hydrate_snapshot(self.with_claim(form))
            store = MemoryStore(); capture_snapshot(store, snapshot, selection=self.selection)
            self.assertEqual(restore_snapshot(store, snapshot.snapshot_id), snapshot)
            self.assertEqual(snapshot.approval_claims[0].verification, "unverified_claim")
            with self.subTest(form=form), self.assertRaises(PolicyNotDefined):
                request_consultant_transition(snapshot, fixture_id(240), str(fixture_id(10)), "Executable")

    def test_d05_missing_evidence_or_executor_is_captured_but_cannot_execute(self):
        for evidence, executor in ((False, True), (True, False), (False, False)):
            snapshot = hydrate_snapshot(self.with_claim(evidence=evidence, executor=executor))
            with self.subTest(evidence=evidence, executor=executor), self.assertRaisesRegex(PermissionError, "no grant"):
                request_consultant_transition(snapshot, fixture_id(240), str(fixture_id(10)), "Executable")

    def test_d05_mistyped_or_dangling_claim_links(self):
        for field, target in (("engagement_id", 2), ("engagement_id", 999), ("executor_id", 2), ("executor_id", 999)):
            raw = self.with_claim()
            raw["approval_claims"][0][field] = fact(str(fixture_id(target))) if field == "executor_id" else str(fixture_id(target))
            with self.subTest(field=field, target=target), self.assertRaises(ReferenceError):
                hydrate_snapshot(raw)
        raw = self.with_claim(); raw["approval_claims"][0]["authority"]["evidence_ref"] = str(fixture_id(3))
        with self.assertRaises(ReferenceError): hydrate_snapshot(raw)

    def test_d05_context_cannot_exceed_subsystem_engagement(self):
        raw = self.with_claim()
        self.find(raw, "consultant")["context"] = {
            "kind": "subsystem", "project_id": str(fixture_id(5)), "subsystem_id": str(fixture_id(7))}
        with self.assertRaisesRegex(ReferenceError, "exceeds subsystem"):
            hydrate_snapshot(raw)

    def test_known_observation_cannot_use_unknown_only_support(self):
        raw = self.raw(); self.evidence(raw, 201, "unknown")
        self.find(raw, "project")["name"] = {"value": "Unsupported known claim", "epistemic_status": "observed", "evidence_ids": [str(fixture_id(201))]}
        with self.assertRaisesRegex(ReferenceError, "observed source"):
            hydrate_snapshot(raw)

    def inferred(self, inputs=(1,)):
        raw = self.raw()
        self.evidence(raw, 201, "unknown")
        self.evidence(raw, 202, "inferred", inputs=inputs)
        self.find(raw, "project")["name"] = {"value": "Explicitly inferred label", "epistemic_status": "inferred", "evidence_ids": [str(fixture_id(202))]}
        return raw

    def test_inference_from_observed_inputs_preserves_conclusion_status(self):
        snapshot = hydrate_snapshot(self.inferred())
        store = MemoryStore(); capture_snapshot(store, snapshot, selection=self.selection)
        restored = restore_snapshot(store, snapshot.snapshot_id)
        self.assertEqual(restored, snapshot)
        self.assertEqual(next(r for r in restored.records if r.kind == "project").name.epistemic_status, "inferred")
        self.assertEqual(next(r for r in restored.records if r.entity_id == fixture_id(202)).derivation.input_evidence_ids, (fixture_id(1),))

    def test_unknown_inputs_can_be_uncertainty_but_not_only_support(self):
        hydrate_snapshot(self.inferred((1, 201)))
        with self.assertRaisesRegex(ReferenceError, "supported inferred assertion"):
            hydrate_snapshot(self.inferred((201,)))

    def test_known_inference_requires_conclusion_not_just_observed_inputs(self):
        raw = self.raw()
        self.find(raw, "project")["name"]["epistemic_status"] = "inferred"
        with self.assertRaisesRegex(ReferenceError, "explicit supported"):
            hydrate_snapshot(raw)

    def test_derivation_cycles_and_unresolved_inputs(self):
        for inputs in ((202,), (999,)):
            with self.subTest(inputs=inputs), self.assertRaises(ReferenceError):
                hydrate_snapshot(self.inferred(inputs))

    def test_existing_future_evidence_guard_remains_active(self):
        raw = self.raw(); evidence = self.evidence(raw, 201)
        evidence["recorded_at"] = (AT + timedelta(seconds=1)).isoformat()
        with self.assertRaisesRegex(ReferenceError, "recorded after"):
            hydrate_snapshot(raw)

    def test_capture_needs_independent_selection_even_with_payload_receipt(self):
        with self.assertRaisesRegex(ReferenceError, "independent verified"):
            capture_snapshot(MemoryStore(), self.snapshot)

    def test_forged_payload_full_file_hash_does_not_establish_verification(self):
        raw = self.raw(); raw["reference_sha256"] = "0" * 64
        raw["reference_verification"]["file_sha256"] = "0" * 64
        structural = hydrate_snapshot(raw)  # Deliberately structural, not trusted ingestion.
        store = MemoryStore()
        with self.assertRaisesRegex(ReferenceError, "selection/hash"):
            capture_snapshot(store, structural, selection=self.selection)
        self.assertFalse(store.state.aggregates)

    def test_wrong_selection_version_and_time_are_rejected(self):
        for updates in ({"dictionary_version": "wrong"}, {"as_of": AT + timedelta(seconds=1)}):
            selection = self.selection.model_copy(update=updates)
            with self.subTest(updates=updates), self.assertRaises(ReferenceError):
                capture_snapshot(MemoryStore(), self.snapshot, selection=selection)

    def test_dictionary_metadata_is_bound_in_addition_to_payload_digest(self):
        raw = self.raw()
        raw["references"]["provenance"]["source_version"] = "tampered"
        raw["records"][0]["source_version"] = "tampered"
        snapshot = hydrate_snapshot(raw)
        with self.assertRaisesRegex(ReferenceError, "selection/hash"):
            capture_snapshot(MemoryStore(), snapshot, selection=self.selection)

    def test_historical_restore_needs_no_original_reference_file(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder); (root / "public").mkdir()
            original = ROOT / "references" / FIXTURE_REFERENCE_PATH
            destination = root / FIXTURE_REFERENCE_PATH
            shutil.copyfile(original, destination)
            inputs = build_fixture_with_selection(root)
            store = MemoryStore(); capture_snapshot(store, inputs.snapshot, selection=inputs.selection)
            destination.unlink()
            with patch("app.infrastructure.enterprise.references.load_references", side_effect=AssertionError("no fresh file read")):
                restored = restore_snapshot(store, inputs.snapshot.snapshot_id)
            self.assertEqual(restored, inputs.snapshot)
            self.assertEqual(restored.reference_verification, inputs.selection)

    def test_historical_capture_without_receipt_is_not_called_verified(self):
        raw = self.raw(); raw["reference_verification"] = None
        store = MemoryStore()
        with store() as uow:
            uow.aggregates.save(VersionedRecord(aggregate_type="enterprise_snapshot",
                aggregate_id=self.snapshot.snapshot_id, version=1, schema_version=self.snapshot.schema_version,
                payload=raw, recorded_at=AT), None)
            uow.commit()
        with self.assertRaisesRegex(ReferenceError, "lacks a verification receipt"):
            restore_snapshot(store, self.snapshot.snapshot_id)

    def test_loader_rejects_selection_outside_validity_window(self):
        with self.assertRaisesRegex(ValueError, "validity window"):
            load_references(ROOT / "references", FIXTURE_REFERENCE_PATH, FIXTURE_REFERENCE_SHA256,
                            AT.replace(year=2101))
