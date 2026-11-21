"""Compatibility checks for shared document identity, using synthetic inputs only."""
import hashlib
import unittest
from pydantic import ValidationError

from app.application.ingest.identity import document_id, subject_reference_id
from tests.test_xlsx_workbook import BINDING


class IdentityFormulas(unittest.TestCase):
    def test_existing_document_formula_is_unchanged(self):
        expected = hashlib.sha256(b"file|synthetic-document").hexdigest()[:20]
        self.assertEqual(document_id("file", "synthetic-document"),
                         "file:xlsx:project_document:" + expected)

    def test_existing_reference_formula_is_unchanged(self):
        b = BINDING
        expected = hashlib.sha256(f"{b.subject_namespace}|{b.subject_ref}".encode()).hexdigest()[:20]
        self.assertEqual(subject_reference_id(b.subject_kind, b.subject_namespace, b.subject_ref),
                         f"ref:{b.subject_kind}:" + expected)

    def test_reference_grammar_uses_existing_binding_contract(self):
        with self.assertRaises(ValidationError):
            subject_reference_id("person", "example", "synthetic")
        with self.assertRaises(ValidationError):
            subject_reference_id("project", "bad/namespace", "synthetic")

    def test_distinct_platforms_remain_distinct(self):
        self.assertNotEqual(document_id("file", "synthetic"), document_id("api", "synthetic"))


if __name__ == "__main__":
    unittest.main()
