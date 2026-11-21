"""Synthetic canaries for the standalone, framework-free privacy boundary."""
import csv
import io
import json
import unittest

from pydantic import ValidationError

from app.application.ingest.workbook_views import OUTLINE_COLUMNS
from app.interfaces.http.document_projection import (
    DocumentResponse, HandleCodec, SOURCE_LABEL, WbsRow, escape_csv_cell,
    outline_csv, project_document, project_outline, project_task,
)
from tests.test_persistence import obj


class ProjectionTests(unittest.TestCase):
    def setUp(self):
        self.codec = HandleCodec()
        self.canary = "SYNTH-PRIVATE-CANARY"

    def test_document_is_an_allowlist_not_object_dump(self):
        source = obj("doc:" + self.canary, kind="project_document", title=self.canary,
                     rels=[("document_of", "ref:project:" + self.canary),
                           ("private_relation", self.canary)],
                     profile=self.canary, blob_path=self.canary, part_number=self.canary)
        before = source.model_dump_json()
        projected = project_document(source, self.codec)
        payload = projected.model_dump()
        self.assertEqual(set(payload), {"object_id", "kind", "assertion", "approved_work", "subjects"})
        self.assertEqual(projected.assertion, "source_record")
        self.assertFalse(projected.approved_work)
        self.assertNotIn(self.canary, projected.model_dump_json())
        self.assertEqual(payload["subjects"][0]["namespace"], "opaque")
        self.assertTrue(payload["subjects"][0]["reference"].startswith("sub_"))
        self.assertEqual(source.model_dump_json(), before)

    def test_task_source_occurrence_never_approved(self):
        projected = project_task(obj("task:" + self.canary, kind="wbs_task", title=self.canary), self.codec)
        self.assertEqual(set(projected.model_dump()), {"object_id", "kind", "assertion", "approved_work"})
        self.assertNotIn(self.canary, projected.model_dump_json())
        self.assertFalse(projected.approved_work)

    def test_wrong_kinds_rejected(self):
        for fn in (project_document, project_task):
            with self.assertRaises(ValueError):
                fn(obj("wrong", kind="arbitrary"), self.codec)

    def test_unapproved_fields_and_truthy_approval_rejected(self):
        handle = self.codec.encode("doc", "synthetic")
        with self.assertRaises(ValidationError):
            DocumentResponse(object_id=handle, title=self.canary)
        with self.assertRaises(ValidationError):
            DocumentResponse(object_id=handle, approved_work=True)
        with self.assertRaises(ValidationError):
            WbsRow(row_kind="task", locator=self.canary)

    def test_handle_domain_separation_validation_and_restart(self):
        first = self.codec.encode("doc", "synthetic")
        self.assertEqual(first, self.codec.encode("doc", "synthetic"))
        self.assertNotEqual(first.split("_", 1)[1], self.codec.encode("task", "synthetic").split("_", 1)[1])
        self.assertNotEqual(first, HandleCodec().encode("doc", "synthetic"))
        self.assertTrue(self.codec.matches("doc", "synthetic", first))
        self.assertFalse(self.codec.matches("doc", "other", first))
        for bad in ("synthetic", "doc_" + "a" * 63, first + "/", first.upper(), "doc_" + "z" * 64):
            self.assertFalse(self.codec.valid("doc", bad))
        with self.assertRaises(ValueError):
            self.codec.encode("unsafe", "synthetic")

    def test_outline_withholds_every_private_cell_and_preserves_topology(self):
        rows = [{k: self.canary for k in OUTLINE_COLUMNS} for _ in range(2)]
        rows[0].update(wbs_code="parent", parent_wbs_code=None, wbs_level=0, row_kind="phase")
        rows[1].update(wbs_code="child", parent_wbs_code="parent", wbs_level=1, row_kind="task")
        safe = project_outline(rows, "doc-synthetic", self.codec)
        self.assertEqual(safe[1].parent_wbs_code, safe[0].wbs_code)
        self.assertEqual([r.wbs_level for r in safe], [0, 1])
        text = json.dumps([r.model_dump() for r in safe]) + outline_csv(safe)
        self.assertNotIn(self.canary, text)
        rendered = list(csv.reader(io.StringIO(outline_csv(safe))))
        self.assertEqual(tuple(rendered[0]), OUTLINE_COLUMNS)
        self.assertEqual(len(rendered), 3)
        self.assertEqual(rendered[1][3], SOURCE_LABEL)
        self.assertEqual(rendered[1][5:], [""] * (len(OUTLINE_COLUMNS) - 5))
        for bad in (True, "1", -1, 65, None):
            self.assertIsNone(project_outline([{"wbs_level": bad}], "doc", self.codec)[0].wbs_level)
        self.assertNotEqual(safe[0].wbs_code, project_outline(rows, "other", self.codec)[0].wbs_code)

    def test_unknown_row_kinds_and_extra_columns_never_escape(self):
        row = project_outline([{"row_kind": self.canary, "unexpected": self.canary}], "doc", self.codec)[0]
        self.assertEqual(row.row_kind, "source_record")
        self.assertNotIn(self.canary, row.model_dump_json())
        with self.assertRaises(TypeError):
            outline_csv([{"name": self.canary}])

    def test_formula_prefixes_and_leading_whitespace(self):
        for value in ("=1+1", "+1", "-2", "@SUM(1)", "\tformula", "\rformula", "\nformula", "  =1", "\t+1"):
            self.assertEqual(escape_csv_cell(value), "'" + value)
        self.assertEqual(escape_csv_cell("normal"), "normal")
        self.assertEqual(escape_csv_cell(None), "")

    def test_no_source_data_in_dto_schema_and_every_field_described(self):
        import app.interfaces.http.document_projection as module
        for name in ("DocumentResponse", "TaskResponse", "TasksResponse", "WbsResponse", "WbsRow", "SubjectLink", "DocumentsResponse"):
            for field in getattr(module, name).model_fields.values():
                self.assertTrue(field.description, name)
