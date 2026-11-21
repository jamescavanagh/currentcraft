"""Public synthetic framework data must hydrate through existing reference objects."""
import copy
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
from app.application.enterprise.services import ReferenceError, hydrate_snapshot
from app.infrastructure.enterprise.wiring import build_fixture_with_selection, fixture_id
from tests.integration.test_enterprise import fact, optional_data


class PublicFrameworkFixture(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.snapshot = build_fixture_with_selection(ROOT / "references").snapshot
        cls.fixture = json.loads((ROOT / "references/public/framework.synthetic.v1.json").read_text())

    def raw_with_framework(self):
        fixture = self.fixture
        data = optional_data(self.snapshot)
        reference_set = next(r for r in data["records"] if r["kind"] == "reference_set")
        reference_set["dictionary_id"] = fixture["reference_set"]["dictionary_id"]
        reference_set["dictionary_version"] = fixture["reference_set"]["dictionary_version"]
        reference_value = next(r for r in data["records"] if r["kind"] == "reference_value")
        reference_value["code"] = fact(fixture["values"][0]["code"])
        for number, item in enumerate(fixture["values"][1:], start=144):
            data["records"].append({
                "kind": "reference_value",
                "entity_id": str(fixture_id(number)),
                "evidence_ids": [str(fixture_id(1))],
                "reference_set_id": reference_set["entity_id"],
                "code": fact(item["code"]),
            })
        return data

    def test_synthetic_public_framework_hydrates_existing_reference_objects(self):
        self.assertEqual(self.fixture["schema_version"], "synthetic-public-framework/v1")
        self.assertEqual(self.fixture["classification"], "synthetic-public-test-fixture")
        self.assertIs(self.fixture["synthetic"], True)
        self.assertEqual(self.fixture["reference_set"]["dictionary_id"], self.snapshot.references.dictionary_id)
        self.assertEqual(self.fixture["reference_set"]["dictionary_version"], self.snapshot.references.version)
        self.assertIn("not an adopted standard", self.fixture["notice"])

        snapshot = hydrate_snapshot(self.raw_with_framework())
        reference_set = next(r for r in snapshot.records if r.kind == "reference_set")
        values = [r for r in snapshot.records if r.kind == "reference_value"]
        self.assertEqual([r.code.value for r in values], [item["code"] for item in self.fixture["values"]])
        self.assertTrue(all(r.reference_set_id == reference_set.entity_id for r in values))
        self.assertTrue(all(r.deprecated.epistemic_status == "unknown" for r in values))
        self.assertNotIn("authority", type(reference_set).model_fields)
        self.assertNotIn("authority", type(values[0]).model_fields)

    def test_duplicate_framework_codes_are_rejected(self):
        data = self.raw_with_framework()
        original = next(r for r in data["records"] if r["kind"] == "reference_value")
        duplicate = copy.deepcopy(original)
        duplicate["entity_id"] = str(fixture_id(146))
        data["records"].append(duplicate)
        with self.assertRaisesRegex(ReferenceError, "duplicate reference code"):
            hydrate_snapshot(data)


if __name__ == "__main__":
    unittest.main()
