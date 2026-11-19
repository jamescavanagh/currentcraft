"""Domain value/type invariants, separate from unresolved operating policy."""
import unittest
import sys
from pathlib import Path
from datetime import datetime, timezone
from decimal import Decimal
from uuid import uuid4
from pydantic import ValidationError
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
from app.domain.shared.identity import ExternalReference
from app.domain.shared.facts import Fact, TimeWindow
from app.domain.shared.quantities import Quantity, UnitRef, SourceMoney
from app.domain.workforce.resource import Resource
from app.domain.employee.employee_entity import Employee
from app.domain.workforce.contributor import Contributor
from app.domain.workforce.agent import Agent
from app.domain.parties.party import Party
from app.domain.parties.client import Client
from app.domain.parties.vendor import Vendor
from app.domain.parties.labor_platform_vendor import LaborPlatformVendor
from app.domain.parties.product_only_vendor import ProductOnlyVendor
from app.domain.project.project_entity import Project
from app.domain.project.project_phase import Phase
from app.domain.product.product_definition import ProductDefinition
from app.domain.product.asset_instance import AssetInstance
from app.domain.document.document import Document
from app.domain.document.drawing import Drawing
from app.domain.commercial.commercial_order import Order
from app.domain.quality.quality_evidence import QualityEvidence
from app.domain.engagements.stakeholder_relationship import Stakeholder
from app.domain.engagements.consulting_engagement import Consultant
from app.domain.engagements.manufacturer_representation import ManufacturerRep
from app.domain.logistics.shipment import ShipmentLine


def fact(value):
    return {"value": value, "epistemic_status": "observed", "evidence_ids": (uuid4(),)}


class ValueContracts(unittest.TestCase):
    def test_business_key_cannot_be_internal_identity(self):
        with self.assertRaises(ValidationError):
            Project(entity_id="PRJ-123")
        identity = uuid4()
        p = Project(entity_id=identity, external_refs=(ExternalReference(namespace="synthetic.erp", key="123"),))
        self.assertEqual(p.entity_id, identity)
        self.assertEqual(p.external_refs[0].key, "123")

    def test_external_namespace_is_part_of_identity(self):
        a = ExternalReference(namespace="synthetic.erp", key="123")
        b = ExternalReference(namespace="synthetic.pm", key="123")
        self.assertNotEqual(a, b)
        p = Project(entity_id=uuid4(), external_refs=(a, b))
        self.assertEqual(len(p.external_refs), 2)
        with self.assertRaises(ValidationError):
            Project(entity_id=uuid4(), external_refs=(a, a))

    def test_missing_requires_reason_known_requires_evidence(self):
        for raw in ({"value": None}, {"value": 0}, {"value": None, "missing_reason": " "},
                    {"value": 0, "missing_reason": "not known", "evidence_ids": [uuid4()]}):
            with self.subTest(raw=raw), self.assertRaises(ValidationError):
                Fact[int].model_validate(raw)
        self.assertIsNone(Fact[int](value=None, epistemic_status="unknown", missing_reason="not recorded").value)

    def test_valid_zero_and_false_are_not_missing(self):
        self.assertEqual(Fact[int](**fact(0)).value, 0)
        self.assertIs(Fact[bool](**fact(False)).value, False)

    def test_empty_names_are_rejected(self):
        for value in ("", "   "):
            with self.subTest(value=value), self.assertRaises(ValidationError):
                Project(entity_id=uuid4(), name=fact(value))

    def test_quantities_are_exact_finite_and_nonnegative(self):
        unit = UnitRef(dictionary_id="synthetic", dictionary_version="1", code="each", dimension="count")
        self.assertEqual(Quantity(amount="0.1234567890123456789", unit=unit).amount,
                         Decimal("0.1234567890123456789"))
        self.assertEqual(Quantity(amount=0, unit=unit).amount, Decimal(0))
        for amount in (-1, 0.1, True, "NaN", "Infinity"):
            with self.subTest(amount=amount), self.assertRaises(ValidationError):
                Quantity(amount=amount, unit=unit)

    def test_quantity_addition_does_not_round_source_precision(self):
        unit = UnitRef(dictionary_id="synthetic", dictionary_version="1", code="each", dimension="count")
        a = Quantity(amount="123456789012345678901234567890.1", unit=unit)
        b = Quantity(amount="0.2", unit=unit)
        self.assertEqual(a.plus(b).amount, Decimal("123456789012345678901234567890.3"))

    def test_units_cannot_be_added_implicitly(self):
        unit = UnitRef(dictionary_id="synthetic", dictionary_version="1", code="each", dimension="count")
        other = unit.model_copy(update={"code": "metre", "dimension": "length"})
        with self.assertRaises(ValueError):
            Quantity(amount=1, unit=unit).plus(Quantity(amount=1, unit=other))

    def test_source_money_retains_source_text_and_context(self):
        raw = "USD 1,234.50 (tax status not supplied)"
        money = SourceMoney(text=fact(raw))
        self.assertEqual(money.text.value, raw)
        self.assertIsNone(money.currency.value)

    def test_time_windows_reject_naive_and_reversed_times(self):
        aware = datetime(2000, 1, 1, tzinfo=timezone.utc)
        later = datetime(2000, 1, 2, tzinfo=timezone.utc)
        self.assertEqual(TimeWindow(start=aware, end=later).start, aware)
        for start, end in ((later, aware), (aware, aware), (aware.replace(tzinfo=None), later)):
            with self.subTest(start=start, end=end), self.assertRaises(ValidationError):
                TimeWindow(start=start, end=end)

    def test_provenance_preserves_separate_recorded_and_valid_times(self):
        eid = uuid4()
        interval = TimeWindow(start="1999-01-01T00:00:00Z", end="2000-01-01T00:00:00Z")
        evidence = QualityEvidence(entity_id=eid, source="synthetic", source_version="v2", locator="source://p4",
            status="inferred", recorded_at="2000-02-01T00:00:00Z",
            derivation={"method_ref":"synthetic://method/v1", "input_evidence_ids":[uuid4()]},
            valid_time={"value": interval, "epistemic_status": "inferred", "evidence_ids": [eid]})
        restored = QualityEvidence.model_validate_json(evidence.model_dump_json())
        self.assertEqual(restored, evidence)
        self.assertNotEqual(restored.recorded_at, restored.valid_time.value.start)

    def test_employee_and_contributor_are_siblings(self):
        self.assertTrue(issubclass(Employee, Resource))
        self.assertTrue(issubclass(Contributor, Resource))
        self.assertFalse(issubclass(Employee, Contributor))
        self.assertFalse(issubclass(Contributor, Employee))
        for kind in ("full_time", "part_time", "temporary"):
            self.assertEqual(Employee(entity_id=uuid4(), employment_kind=fact(kind)).employment_kind.value, kind)

    def test_resources_and_roles_never_grant_permission(self):
        for cls in (Employee, Contributor, Agent):
            resource = cls(entity_id=uuid4())
            for permission in ("release", "approve_design", "unknown.permission"):
                self.assertFalse(resource.permits(permission))
        for cls in (Stakeholder, Consultant, ManufacturerRep):
            self.assertFalse(issubclass(cls, Party))
            self.assertNotIn("approval_authority", cls.model_fields)

    def test_lifecycle_phase_has_no_physics_phase_field(self):
        phase = Phase(entity_id=uuid4(), project_id=uuid4())
        with self.assertRaises(ValidationError):
            Phase(**phase.model_dump(), physics_phase=0.5)

    def test_catalog_and_asset_have_separate_identities(self):
        product = ProductDefinition(entity_id=uuid4())
        asset = AssetInstance(entity_id=uuid4(), project_id=uuid4(), product_definition_id=product.entity_id)
        self.assertNotEqual(product.entity_id, asset.entity_id)
        self.assertNotIn("serial", ProductDefinition.model_fields)

    def test_order_and_document_are_separate_and_unapproved(self):
        self.assertFalse(issubclass(Order, Document))
        document = Document(entity_id=uuid4(), project_id=uuid4())
        with self.assertRaises(PermissionError):
            document.transition("approved")
        with self.assertRaises(NotImplementedError):
            document.require_accepted_definition()
        self.assertEqual(Drawing.SCHEMA_STATUS, "unreviewed-scaffold")

    def test_vendor_classifications_do_not_enforce_overlap(self):
        party_id = uuid4()
        records = [cls(entity_id=uuid4(), party_id=party_id) for cls in (Client, Vendor, LaborPlatformVendor, ProductOnlyVendor)]
        self.assertEqual({r.party_id for r in records}, {party_id})
        self.assertEqual(len({r.entity_id for r in records}), 4)

    def test_shipment_line_requires_exactly_one_supported_variant(self):
        base = {"entity_id": uuid4(), "shipment_id": uuid4()}
        with self.assertRaises(ValidationError):
            ShipmentLine(**base)
        asset = ShipmentLine(**base, asset_id=fact(uuid4()))
        self.assertIsNone(asset.quantity.value)
        with self.assertRaises(ValidationError):
            ShipmentLine(**base, asset_id=fact(uuid4()), product_definition_id=fact(uuid4()))

    def test_entity_is_immutable_closed_and_versioned(self):
        project = Project(entity_id=uuid4())
        with self.assertRaises(ValidationError):
            project.entity_id = uuid4()
        for raw in ({"entity_id": uuid4(), "record_version": 0}, {"entity_id": uuid4(), "extra_field": True}):
            with self.assertRaises(ValidationError):
                Project(**raw)
