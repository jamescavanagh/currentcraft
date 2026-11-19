"""Allowlisted hydration, provenance, denied rights and transactional snapshot capture."""
import copy
import hashlib
import json
import tempfile
import unittest
import sys
from pathlib import Path
from pydantic import ValidationError
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
from app.application.enterprise.contracts import ENTITY_TYPES
from app.application.enterprise.services import (ReferenceError, PolicyNotDefined, hydrate_snapshot,
    capture_snapshot, restore_snapshot, request_transition)
from app.application.persistence.contracts import VersionConflict
from app.application.process.contracts import AuthorityRef
from app.infrastructure.enterprise.wiring import AT, FIXTURE_REFERENCE_SHA256, FIXTURE_REFERENCE_PATH, build_fixture, build_fixture_with_selection, fixture_id
from app.infrastructure.enterprise.references import load_references
from app.infrastructure.persistence.memory import MemoryStore

ROOT = Path(__file__).resolve().parents[2]


def fact(value):
    return {"value": value, "epistemic_status": "observed", "evidence_ids": [str(fixture_id(1))]}


def optional_data(snapshot):
    """Independent optional branches, kept outside the minimal bootstrap fixture."""
    data = snapshot.model_dump(mode="json")
    project, party, evidence = (str(fixture_id(n)) for n in (5, 2, 1))
    unit = copy.deepcopy(data["references"]["units"][0])
    def add(kind, number, **fields):
        data["records"].append({"kind": kind, "entity_id": str(fixture_id(number)),
                               "evidence_ids": [evidence], **fields})
    add("contributor", 100, party_id=fact(party), provider_party_id=fact(party))
    add("agent", 101, model_reference=fact("synthetic-model-v1"))
    for number, kind in enumerate(("client", "vendor", "product_only_vendor",
        "professional_services_manufacturer_vendor", "labor_platform_vendor",
        "subcontractor_freelancer_vendor"), 102):
        add(kind, number, party_id=party)
    add("stakeholder", 108, party_id=party, context={"kind":"project","project_id":project}, role=fact("synthetic.observer"))
    add("consultant", 109, party_id=party, context={"kind":"project","project_id":project}, role=fact("synthetic.consultant"))
    add("manufacturer_rep", 110, representative_party_id=party, manufacturer_party_id=party, project_id=fact(project))
    add("wbs", 111, project_id=project, code=fact("SYNTHETIC-WBS"))
    add("document", 112, project_id=project, name=fact("Synthetic source document"))
    add("bom", 113, project_id=project, stage=fact("rom"))
    add("product_definition", 120, name=fact("Synthetic bulk material"), is_bulk=fact(True))
    add("bom_line", 114, bom_id=str(fixture_id(113)), product_definition_id=str(fixture_id(120)),
        quantity=fact({"amount": "0", "unit": unit}))
    add("shipment", 115, project_id=project)
    add("shipment_line", 116, shipment_id=str(fixture_id(115)),
        product_definition_id=fact(str(fixture_id(120))), quantity=fact({"amount": "3.25", "unit": unit}))
    add("shipment_line", 121, shipment_id=str(fixture_id(115)), asset_id=fact(str(fixture_id(9))))
    add("calendar_booking", 117, project_id=project, resource_id=str(fixture_id(3)),
        task_id=str(fixture_id(8)), window={"start": "2000-01-01T01:00:00Z", "end": "2000-01-01T02:00:00Z"})
    add("rfi", 118, project_id=project, question=fact("Synthetic question?"),
        impact_ids=[str(fixture_id(9)), str(fixture_id(112))])
    add("order", 119, project_id=project, counterparty_id=fact(party), document_ids=[str(fixture_id(112))])
    return data


class SnapshotIntegration(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        inputs = build_fixture_with_selection(ROOT / "references")
        cls.snapshot, cls.selection = inputs.snapshot, inputs.selection

    def raw(self):
        return self.snapshot.model_dump(mode="json")

    def test_fixture_is_reproducible_and_minimal(self):
        self.assertEqual(self.snapshot, build_fixture(ROOT / "references"))
        self.assertEqual(len(self.snapshot.records), 9)
        self.assertEqual(len(self.snapshot.executions), 1)
        self.assertFalse(any(r.kind in {"bom", "order", "calendar_booking"} for r in self.snapshot.records))

    def test_application_persistence_roundtrip_and_outbox(self):
        store = MemoryStore()
        saved = capture_snapshot(store, self.snapshot, selection=self.selection)
        self.assertEqual(saved.version, 1)
        self.assertEqual(restore_snapshot(store, self.snapshot.snapshot_id), self.snapshot)
        with store() as uow:
            events = uow.outbox.pending()
            self.assertEqual(len(uow.aggregates.history("enterprise_snapshot", self.snapshot.snapshot_id)), 1)
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].envelope["epistemic_status"], "simulated")
        self.assertIsNone(events[0].published_at)

    def test_compare_and_swap_preserves_history_and_events(self):
        store = MemoryStore()
        capture_snapshot(store, self.snapshot, selection=self.selection)
        with self.assertRaises(VersionConflict):
            capture_snapshot(store, self.snapshot, selection=self.selection)
        self.assertEqual(len(store.state.outbox), 1)
        self.assertEqual(capture_snapshot(store, self.snapshot, expected_version=1, selection=self.selection).version, 2)
        self.assertEqual(len(store.state.outbox), 2)

    def test_changed_entity_requires_a_new_immutable_revision(self):
        store = MemoryStore()
        capture_snapshot(store, self.snapshot, selection=self.selection)
        raw = self.raw()
        raw["records"][4]["name"] = fact("Revised synthetic project name")
        changed = hydrate_snapshot(raw)
        with self.assertRaises(VersionConflict):
            capture_snapshot(store, changed, expected_version=1, selection=self.selection)
        self.assertEqual(restore_snapshot(store, self.snapshot.snapshot_id), self.snapshot)
        raw["records"][4]["record_version"] = 2
        revised = hydrate_snapshot(raw)
        capture_snapshot(store, revised, expected_version=1, selection=self.selection)
        with store() as uow:
            history = uow.aggregates.history("enterprise_entity", fixture_id(5))
            self.assertEqual([r.version for r in history], [1, 2])
            self.assertEqual(history[0].payload["name"]["value"], "Synthetic project")
        self.assertEqual(restore_snapshot(store, self.snapshot.snapshot_id), revised)

    def test_outbox_failure_rolls_back_aggregate(self):
        store = MemoryStore()
        def failing_factory():
            uow = store()
            def fail(*args):
                raise RuntimeError("synthetic outbox failure")
            uow.outbox.add = fail
            return uow
        with self.assertRaisesRegex(RuntimeError, "synthetic outbox"):
            capture_snapshot(failing_factory, self.snapshot, selection=self.selection)
        self.assertFalse(store.state.aggregates)
        self.assertFalse(store.state.outbox)

    def test_all_optional_types_hydrate_separately(self):
        snapshot = hydrate_snapshot(optional_data(self.snapshot))
        self.assertEqual({type(r) for r in snapshot.records}, set(ENTITY_TYPES))
        store = MemoryStore()
        capture_snapshot(store, snapshot, selection=self.selection)
        self.assertEqual(restore_snapshot(store, snapshot.snapshot_id), snapshot)

    def test_unknown_record_type_and_fields_are_rejected(self):
        for field, value in (("kind", "python.import.anything"), ("approval_authority", True),
                             ("name", {"value": [], "evidence_ids": [str(fixture_id(1))]})):
            raw = self.raw()
            raw["records"][4][field] = value
            with self.subTest(field=field), self.assertRaises(ValidationError):
                hydrate_snapshot(raw)

    def test_dangling_and_mistyped_project_references(self):
        for target in (fixture_id(404), fixture_id(3)):
            raw = self.raw()
            raw["records"][7]["project_id"] = str(target)
            with self.subTest(target=target), self.assertRaises(ReferenceError):
                hydrate_snapshot(raw)

    def test_duplicate_record_ids(self):
        raw = self.raw()
        raw["records"].append(copy.deepcopy(raw["records"][4]))
        with self.assertRaisesRegex(ReferenceError, "duplicate"):
            hydrate_snapshot(raw)

    def test_dangling_field_evidence(self):
        raw = self.raw()
        raw["records"][4]["name"]["evidence_ids"] = [str(fixture_id(404))]
        with self.assertRaises(ReferenceError):
            hydrate_snapshot(raw)

    def test_cross_project_links(self):
        raw = self.raw()
        other = copy.deepcopy(raw["records"][4])
        other["entity_id"] = str(fixture_id(200))
        raw["records"].append(other)
        raw["records"][6]["project_id"] = other["entity_id"]
        with self.assertRaisesRegex(ReferenceError, "cross-project"):
            hydrate_snapshot(raw)

    def test_asset_definition_must_exist_and_be_nonbulk(self):
        for is_bulk in (fact(True), {"value": None, "epistemic_status": "unknown", "missing_reason": "not supplied"}):
            raw = self.raw()
            raw["records"][3]["is_bulk"] = is_bulk
            with self.subTest(is_bulk=is_bulk), self.assertRaisesRegex(ReferenceError, "non-bulk"):
                hydrate_snapshot(raw)

    def test_capture_does_not_allocate_or_manufacture_stock(self):
        store = MemoryStore()
        capture_snapshot(store, self.snapshot, selection=self.selection)
        self.assertFalse(store.state.stock)
        self.assertFalse(store.state.reservations)
        self.assertEqual(sum(r.kind == "asset_instance" for r in self.snapshot.records), 1)
        for effect in ("produces", "consumes"):
            raw = self.raw()
            incidence = raw["executions"][0]["execution"]["incidence"][0]
            incidence["effect"] = effect
            if effect == "produces":
                incidence["state_after"] = "synthetic.captured"
            with self.subTest(effect=effect), self.assertRaisesRegex(ReferenceError, "physical units"):
                hydrate_snapshot(raw)

    def test_units_are_checked_against_selected_dictionary(self):
        raw = optional_data(self.snapshot)
        line = next(r for r in raw["records"] if r["kind"] == "bom_line")
        line["quantity"]["value"]["unit"]["code"] = "unselected.unit"
        with self.assertRaisesRegex(ReferenceError, "unit"):
            hydrate_snapshot(raw)

    def test_phase_does_not_automatically_become_execution_stage(self):
        raw = self.raw()
        raw["stage_mappings"] = []
        with self.assertRaisesRegex(ReferenceError, "mapping"):
            hydrate_snapshot(raw)

    def test_unselected_process_definition_is_rejected(self):
        raw = self.raw()
        raw["executions"][0]["execution"]["process"]["name"] = "Unselected process meaning"
        with self.assertRaisesRegex(ReferenceError, "process"):
            hydrate_snapshot(raw)

    def test_missing_capability_evidence_is_rejected(self):
        raw = self.raw()
        raw["capabilities"][0]["binding"]["evidence_ref"] = None
        with self.assertRaises(ReferenceError):
            hydrate_snapshot(raw)

    def test_people_and_parties_cannot_be_operands(self):
        for target, kind in ((2, "party"), (100, "contributor")):
            raw = optional_data(self.snapshot)
            raw["executions"][0]["execution"]["incidence"] = [
                {"object_id": str(fixture_id(target)), "object_kind": kind, "effect": "reads"}]
            with self.subTest(kind=kind), self.assertRaisesRegex(ReferenceError, "operands"):
                hydrate_snapshot(raw)

    def test_duplicate_execution_ids(self):
        raw = self.raw()
        raw["executions"].append(copy.deepcopy(raw["executions"][0]))
        with self.assertRaisesRegex(ReferenceError, "execution ID"):
            hydrate_snapshot(raw)

    def test_missing_and_naive_execution_time_are_rejected(self):
        for value in (None, "2000-01-01T00:00:00"):
            raw = self.raw()
            raw["executions"][0]["execution"]["occurred_at"] = value
            with self.subTest(value=value), self.assertRaisesRegex(ReferenceError, "timestamp"):
                hydrate_snapshot(raw)

    def test_undefined_buffer_workflow_is_blocked(self):
        raw = self.raw()
        raw["executions"][0]["execution"]["at_buffer"] = "synthetic.unresolved"
        with self.assertRaisesRegex(ReferenceError, "buffer"):
            hydrate_snapshot(raw)

    def test_capture_revalidates_even_model_copy_bypasses(self):
        store = MemoryStore()
        bad = self.snapshot.model_copy(update={"records": self.snapshot.records + (self.snapshot.records[0],)})
        with self.assertRaises(ReferenceError):
            capture_snapshot(store, bad, selection=self.selection)
        self.assertFalse(store.state.aggregates)

    def test_all_readiness_targets_block_without_authority(self):
        for target in ("Conditional", "Ready", "Executable", "Returned", "unknown"):
            with self.subTest(target=target), self.assertRaisesRegex(PermissionError, "authority is missing"):
                request_transition(self.snapshot, str(fixture_id(10)), target)

    def test_role_scope_and_evidence_are_not_an_approved_grant(self):
        authority = AuthorityRef(holder_role="synthetic.executor", scope="release", evidence_ref=str(fixture_id(1)))
        with self.assertRaises(PolicyNotDefined):
            request_transition(self.snapshot, str(fixture_id(10)), "Executable", authority, fixture_id(3))

    def test_ai_cannot_supply_human_authority(self):
        snapshot = hydrate_snapshot(optional_data(self.snapshot))
        authority = AuthorityRef(holder_role="synthetic.executor", scope="release", evidence_ref=str(fixture_id(1)))
        with self.assertRaisesRegex(PermissionError, "human executor"):
            request_transition(snapshot, str(fixture_id(10)), "Executable", authority, fixture_id(101))

    def test_unevidenced_authority_is_rejected(self):
        authority = AuthorityRef(holder_role="synthetic.executor", scope="release")
        with self.assertRaisesRegex(PermissionError, "evidence"):
            request_transition(self.snapshot, str(fixture_id(10)), "Executable", authority, fixture_id(3))


class ReferenceLoading(unittest.TestCase):
    def test_pinned_synthetic_reference_loads(self):
        selected = load_references(ROOT / "references", FIXTURE_REFERENCE_PATH,
                                   FIXTURE_REFERENCE_SHA256, AT)
        self.assertTrue(selected.dictionary.synthetic)

    def test_wrong_full_file_hash_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "SHA-256"):
            load_references(ROOT / "references", FIXTURE_REFERENCE_PATH, "0" * 64, AT)

    def test_root_must_be_absolute_and_path_cannot_escape(self):
        for root, path in ((Path("references"), "public/a.json"), (ROOT / "references", "../pyproject.toml")):
            with self.subTest(path=path), self.assertRaises(ValueError):
                load_references(root, path, "0" * 64, AT)

    def test_unsupported_dictionary_fields_and_types_are_rejected(self):
        original = json.loads((ROOT / "references/public/enterprise.synthetic.v1.1.json").read_text())
        cases = []
        extra = copy.deepcopy(original); extra["python_class"] = "untrusted.module:Class"; cases.append(extra)
        wrong = copy.deepcopy(original); wrong["units"][0]["dimension"] = []; cases.append(wrong)
        stale = copy.deepcopy(original); stale["stages"] = ["tampered"]; cases.append(stale)
        for data in cases:
            with self.subTest(data=data), tempfile.TemporaryDirectory() as folder:
                root = Path(folder)
                raw = json.dumps(data).encode()
                (root / "ref.json").write_bytes(raw)
                with self.assertRaises(ValueError):
                    load_references(root, "ref.json", hashlib.sha256(raw).hexdigest(), AT)

    def test_duplicate_json_keys_and_duplicate_unit_ids_are_rejected(self):
        original = (ROOT / "references/public/enterprise.synthetic.v1.1.json").read_text()
        raw = original.replace('"synthetic": true', '"synthetic": true, "synthetic": true').encode()
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder); (root / "ref.json").write_bytes(raw)
            with self.assertRaisesRegex(ValueError, "duplicate"):
                load_references(root, "ref.json", hashlib.sha256(raw).hexdigest(), AT)
        data = json.loads(original); data["units"].append(copy.deepcopy(data["units"][0]))
        with self.assertRaisesRegex(ValidationError, "duplicate unit"):
            from app.application.enterprise.contracts import ReferenceDictionary
            ReferenceDictionary.model_validate(data)
