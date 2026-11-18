"""Wire-schema/Pydantic agreement for expressible rules; explicit tests of application limits."""
from datetime import datetime
from decimal import Decimal
import hashlib
import json
from pathlib import Path
import sys
import unittest
from jsonschema import Draft202012Validator, FormatChecker
from pydantic import ValidationError

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
from app.domain.shared.facts import Fact, DateBounds
from app.domain.shared.identity import Text
from app.domain.shared.quantities import Quantity, UnitRef
from app.domain.quality.quality_evidence import QualityEvidence
from app.domain.logistics.shipment import ShipmentLine
from app.application.enterprise.contracts import EnterpriseSnapshot, ConsultantApprovalClaim
from app.application.enterprise.services import hydrate_snapshot_json, ReferenceError
from app.infrastructure.enterprise.wiring import fixture_id, build_fixture


def known(value):
    return {"value": value, "epistemic_status": "observed", "evidence_ids": [str(fixture_id(1))]}


def missing():
    return {"value": None, "epistemic_status": "unknown", "missing_reason": "not recorded"}


class SchemaParity(unittest.TestCase):
    def validator(self, model):
        schema = model.model_json_schema()
        Draft202012Validator.check_schema(schema)
        return Draft202012Validator(schema, format_checker=FormatChecker())

    def assert_parity(self, model, vectors):
        validator = self.validator(model)
        for expected, raw in vectors:
            with self.subTest(model=model.__name__, raw=raw):
                schema_ok = validator.is_valid(raw)
                try:
                    model.model_validate_json(json.dumps(raw))
                    model_ok = True
                except (ValueError, TypeError):
                    model_ok = False
                self.assertEqual((schema_ok, model_ok), (expected, expected))

    def test_fact_null_reason_status_and_evidence_rules(self):
        self.assert_parity(Fact[Text], [
            (True, missing()), (True, known("source text")),
            (False, {"value": None, "epistemic_status": "unknown"}),
            (False, {"value": None, "epistemic_status": "unknown", "missing_reason": " "}),
            (False, {**missing(), "epistemic_status": "observed"}),
            (False, {**known("text"), "epistemic_status": "unknown"}),
            (False, {**known("text"), "missing_reason": "contradiction"}),
            (False, {**known("text"), "evidence_ids": []}),
            (False, {**known("text"), "evidence_ids": [str(fixture_id(1))] * 2}),
            (False, {"value": "legacy value", "evidence_ids": [str(fixture_id(1))]})])
        self.assert_parity(Fact[int], [(True, known(0)), (True, missing())])

    def test_shipment_variants_respect_fact_wrappers_and_omitted_defaults(self):
        unit = UnitRef(dictionary_id="synthetic", dictionary_version="1", code="each", dimension="count").model_dump(mode="json")
        base = {"entity_id": str(fixture_id(300)), "shipment_id": str(fixture_id(301))}
        asset, product = known(str(fixture_id(9))), known(str(fixture_id(4)))
        quantity = known({"amount": "1.25", "unit": unit})
        self.assert_parity(ShipmentLine, [
            (False, base), (True, {**base, "asset_id": asset}),
            (True, {**base, "asset_id": asset, "product_definition_id": missing(), "quantity": missing()}),
            (True, {**base, "product_definition_id": product, "quantity": quantity}),
            (False, {**base, "product_definition_id": product}),
            (False, {**base, "quantity": quantity}),
            (False, {**base, "asset_id": asset, "product_definition_id": product, "quantity": quantity}),
            (False, {**base, "asset_id": asset, "quantity": quantity})])

    def test_source_hash_and_missing_reason_pairing_including_defaults(self):
        base = {"entity_id": str(fixture_id(1)), "source": "synthetic", "source_version": "1",
                "locator": "synthetic://source/v1", "status": "observed", "recorded_at": "2000-01-01T00:00:00Z"}
        self.assert_parity(QualityEvidence, [
            (True, base), (True, {**base, "source_sha256": None}),
            (True, {**base, "source_sha256": "a" * 64, "source_sha256_missing_reason": None}),
            (False, {**base, "source_sha256": "a" * 64}),
            (False, {**base, "source_sha256": None, "source_sha256_missing_reason": None}),
            (False, {**base, "source_sha256": None, "source_sha256_missing_reason": " "}),
            (False, {**base, "source_sha256": "bad", "source_sha256_missing_reason": None})])

    def test_inferred_evidence_requires_explicit_derivation(self):
        base = {"entity_id": str(fixture_id(1)), "source": "synthetic", "source_version": "1",
                "locator": "synthetic://source/v1", "status": "inferred", "recorded_at": "2000-01-01T00:00:00Z"}
        derivation = {"method_ref": "synthetic://method/v1", "input_evidence_ids": [str(fixture_id(2))]}
        self.assert_parity(QualityEvidence, [
            (False, base), (True, {**base, "derivation": derivation}),
            (False, {**base, "status": "observed", "derivation": derivation}),
            (False, {**base, "derivation": {**derivation, "input_evidence_ids": []}}),
            (False, {**base, "derivation": {**derivation, "input_evidence_ids": [str(fixture_id(2))] * 2}})])

    def test_quantity_json_is_decimal_string_only(self):
        unit = {"dictionary_id": "synthetic", "dictionary_version": "1", "code": "each", "dimension": "count"}
        accepted = ["0", "1", "1.123456789012345678901234567890", "+1e-3", "-0.000", ".25", "1."]
        rejected = [0, 1, 1.0, 0.25, True, False, None, "-1", "NaN", "Infinity", "", " 1", "1\n", "1_000", float("nan"), float("inf")]
        self.assert_parity(Quantity, [(True, {"amount": x, "unit": unit}) for x in accepted] +
                           [(False, {"amount": x, "unit": unit}) for x in rejected])

    def test_quantity_python_convenience_input_has_explicit_limits(self):
        unit = UnitRef(dictionary_id="synthetic", dictionary_version="1", code="each", dimension="count")
        for value in (0, 1, Decimal("0.123456789012345678901234567890"), "1.25"):
            with self.subTest(value=value):
                quantity = Quantity(amount=value, unit=unit)
                self.assertIsInstance(quantity.model_dump(mode="json")["amount"], str)
                self.assertEqual(Quantity.model_validate_json(quantity.model_dump_json()), quantity)
        for value in (1.0, 0.25, True, Decimal("NaN"), Decimal("Infinity"), Decimal("-1"), -1):
            with self.subTest(value=value), self.assertRaises(ValidationError):
                Quantity(amount=value, unit=unit)

    def test_date_ordering_is_honestly_model_only(self):
        raw = {"starts_on": known("2000-01-02"), "ends_on": known("2000-01-01")}
        self.assertTrue(self.validator(DateBounds).is_valid(raw))
        with self.assertRaisesRegex(ValidationError, "end precedes start"):
            DateBounds.model_validate_json(json.dumps(raw))

    def test_authority_claim_schema_never_labels_a_grant_verified(self):
        base = {"claim_id": str(fixture_id(240)), "engagement_id": str(fixture_id(109)),
            "context": {"kind": "project", "project_id": str(fixture_id(5))},
            "authority": {"holder_role": "synthetic.consultant", "scope": "approve_design"}}
        known_authority = {**base["authority"], "evidence_ref": str(fixture_id(1))}
        self.assert_parity(ConsultantApprovalClaim, [
            (True, base),
            (False, {**base, "verification": "verified_grant"}),
            (False, {**base, "authority": known_authority}),
            (True, {**base, "authority": known_authority, "authority_evidence_missing_reason": None}),
            (False, {**base, "authority_evidence_missing_reason": None})])

    def test_entire_generated_snapshot_schema_is_read_and_matches_model(self):
        path = ROOT / "docs/contracts/schemas/agency/EnterpriseSnapshot.schema.json"
        raw = path.read_bytes()  # Full local read; no page-text truncation.
        schema = json.loads(raw)
        self.assertEqual(schema, EnterpriseSnapshot.model_json_schema())
        Draft202012Validator.check_schema(schema)
        snapshot = build_fixture(ROOT / "references")
        validator = Draft202012Validator(schema, format_checker=FormatChecker())
        validator.validate(snapshot.model_dump(mode="json"))
        def check_refs(value):
            if isinstance(value, dict):
                if "$ref" in value:
                    self.assertTrue(value["$ref"].startswith("#/"))
                    target = schema
                    for part in value["$ref"][2:].split("/"):
                        target = target[part.replace("~1", "/").replace("~0", "~")]
                for child in value.values(): check_refs(child)
            elif isinstance(value, list):
                for child in value: check_refs(child)
        check_refs(schema)
        self.assertGreater(len(raw), 10000)
        self.assertEqual(len(hashlib.sha256(raw).hexdigest()), 64)

    def test_cross_record_resolution_is_not_claimed_by_json_schema(self):
        snapshot = build_fixture(ROOT / "references")
        raw = snapshot.model_dump(mode="json")
        raw["records"][7]["project_id"] = str(fixture_id(999))
        self.validator(EnterpriseSnapshot).validate(raw)
        EnterpriseSnapshot.model_validate_json(json.dumps(raw))
        with self.assertRaises(ReferenceError):
            hydrate_snapshot_json(json.dumps(raw))
