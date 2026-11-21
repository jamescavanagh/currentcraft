"""Required combined synthetic HTTP acceptance, not live-service evidence."""
from __future__ import annotations

import asyncio
import csv
import io
import logging
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from fastapi.testclient import TestClient

from app.application.ingest.workbook_views import OUTLINE_COLUMNS
from app.application.queries.documents import (
    document_outline, document_tasks, documents_for_reference,
)
from app.infrastructure.ingest.directory_blobs import DirectoryBlobStore
from app.infrastructure.ingest.intake_receipts import SqliteIntakeReceipts
from app.infrastructure.ingest.wiring import build_durable_ingest
from app.infrastructure.messaging import InMemoryDurableBroker
from app.infrastructure.persistence import build_memory
from app.interfaces.http.app import create_app
from app.interfaces.http.container import Container
from app.interfaces.http.document_projection import project_outline, project_task
from app.interfaces.http.settings import Settings
from tests.test_durable_messaging import spec
from tests.test_xlsx_workbook import BINDING, CFG, PROFILE, workbook


class IntegratedApiAcceptance(unittest.TestCase):
    def setUp(self):
        self.directory = self.enterContext(TemporaryDirectory())
        self.store = build_memory()
        self.broker = InMemoryDurableBroker()
        self.blobs = DirectoryBlobStore(Path(self.directory) / "blobs")
        self.receipts = SqliteIntakeReceipts(str(Path(self.directory) / "receipts.sqlite3"))
        self.token = "synthetic-e2e-bearer-canary"
        self.source = "synthetic-e2e-private-source"
        self.log = io.StringIO()
        handler = logging.StreamHandler(self.log)
        logging.getLogger().addHandler(handler)
        self.addCleanup(logging.getLogger().removeHandler, handler)
        self.responses = []

        async def ready():
            return True

        async def close():
            pass

        settings = Settings("synthetic-e2e-dsn", ("nats://example.invalid",),
                            "synthetic-e2e-nats", self.token)
        self.container = Container(settings, ready, ready, close,
                                   uow_factory=self.store, intake_broker=self.broker,
                                   blobs=self.blobs, receipts=self.receipts)

        async def factory():
            return self.container

        self.client = self.enterContext(TestClient(create_app(factory),
                                                   raise_server_exceptions=False))
        self.auth = {"Authorization": "Bearer " + self.token}
        self.worker = build_durable_ingest(
            broker=self.broker, uow_factory=self.store, blobs=self.blobs,
            config=CFG, spec=spec("synthetic-http-e2e"), profiles=(PROFILE,))
        asyncio.run(self.broker.ensure_consumer(self.worker.spec))

    def response(self, response, status=200):
        self.assertEqual(response.status_code, status, response.text)
        self.responses.append(response)
        return response

    def get(self, path):
        return self.response(self.client.get(path, headers=self.auth))

    def upload(self, data, *, revision="synthetic-e2e-one"):
        fields = {
            "source_id": self.source, "format": "xlsx", "mapping": PROFILE.name,
            "subject_kind": BINDING.subject_kind,
            "subject_namespace": BINDING.subject_namespace,
            "subject_ref": BINDING.subject_ref,
            "document_type": BINDING.document_type, "revision_label": revision,
        }
        result = self.response(self.client.post(
            "/v1/intake/documents", data=fields, headers=self.auth,
            files={"file": ("synthetic-private-name.xlsx", data,
                            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
        ), 202).json()
        self.assertIn("not extracted", result["detail"])
        self.assertRegex(result["event_id"], r"^intake_[0-9a-f]{32}$")
        self.assertEqual(result["status_url"], "/v1/intake/" + result["event_id"])
        return result

    def status(self, receipt, expected):
        result = self.get(receipt["status_url"]).json()
        self.assertEqual(result["status"], expected)
        self.assertIn("not approved work", result["detail"])

    def run_worker(self):
        asyncio.run(self.worker.run_batch())

    def heads(self):
        return documents_for_reference(
            self.store, BINDING.subject_kind, BINDING.subject_namespace, BINDING.subject_ref)

    def snapshot(self):
        # Read-only evidence of worker-created records, never seed repository state.
        with self.store() as uow:
            return {
                kind: tuple((obj.object_id, obj.digest()) for obj in uow.objects.by_kind(kind))
                for kind in ("project_document", "document_revision", "wbs_task", "phase_scope")
            }

    def assert_safe(self):
        public = self.log.getvalue() + "".join(
            response.text + str(response.headers) for response in self.responses)
        for canary in (
            self.token, self.source, "synthetic-e2e-dsn", "synthetic-e2e-nats",
            "synthetic-private-name.xlsx", self.directory, PROFILE.name,
            BINDING.subject_ref, BINDING.subject_namespace, "Grid!", "Site walk", "SW-1",
        ):
            self.assertNotIn(canary, public)

    def assert_reads(self, head):
        # Private initial discovery is allowed; no new public listing endpoint.
        handle = self.container.handles.encode("doc", head.object_id)
        base = "/v1/documents/" + handle
        document = self.get(base).json()
        self.assertEqual(document["object_id"], handle)
        self.assertEqual(document["assertion"], "source_record")
        self.assertIs(document["approved_work"], False)
        tasks = self.get(base + "/tasks").json()
        expected = document_tasks(self.store, head.object_id)
        self.assertTrue(expected)
        self.assertFalse(tasks["all_revisions"])
        self.assertEqual(tasks["assertion"], "source_records_not_approved_work")
        self.assertEqual(tasks["tasks"], [
            project_task(task, self.container.handles).model_dump(mode="json")
            for task in expected])
        for task in tasks["tasks"]:
            self.assertIs(task["approved_work"], False)
            self.assertEqual(task["assertion"], "source_record")

        outline = self.get(base + "/wbs").json()
        expected_rows = project_outline(
            document_outline(self.store, head.object_id), head.object_id, self.container.handles)
        self.assertTrue(expected_rows)
        self.assertEqual(outline["columns"], list(OUTLINE_COLUMNS))
        self.assertEqual(outline["assertion"], "source_records_not_approved_work")
        self.assertEqual(outline["rows"], [row.model_dump(mode="json") for row in expected_rows])
        rendered = list(csv.reader(io.StringIO(self.get(base + "/wbs?format=csv").text)))
        self.assertEqual(tuple(rendered[0]), OUTLINE_COLUMNS)
        self.assertEqual(rendered[1:], [
            ["" if row[key] is None else str(row[key]) for key in OUTLINE_COLUMNS]
            for row in outline["rows"]])

        self.assertEqual(len(document["subjects"]), 1)
        subject = document["subjects"][0]
        self.assertEqual(subject["namespace"], "opaque")
        self.assertRegex(subject["reference"], r"^sub_[0-9a-f]{64}$")
        found = self.get("/v1/subjects/{subject_kind}/{namespace}/{reference}/documents".format(
            **subject)).json()
        self.assertEqual(found["documents"], [document])
        return base, {task["object_id"] for task in tasks["tasks"]}

    def test_http_upload_worker_status_reads_revisions_and_retry(self):
        self.assertEqual(self.heads(), ())
        first = self.upload(workbook())
        self.assertFalse(first["duplicate"])
        self.status(first, "pending")
        self.assertEqual(self.heads(), ())  # A 202 has not extracted anything.
        self.run_worker()
        self.status(first, "processed")
        head, = self.heads()
        base, first_tasks = self.assert_reads(head)

        # Changed source bytes and explicit revision, not a manually seeded head.
        second = self.upload(workbook(Side={"A1": "synthetic-e2e-revised"}),
                             revision="synthetic-e2e-two")
        self.assertNotEqual(first["event_id"], second["event_id"])
        self.status(second, "pending")
        self.run_worker()
        self.status(second, "processed")
        next_head, = self.heads()
        self.assertEqual(next_head.object_id, head.object_id)
        next_base, current_tasks = self.assert_reads(next_head)
        self.assertEqual(next_base, base)
        self.assertTrue(first_tasks.isdisjoint(current_tasks))
        all_tasks = self.get(base + "/tasks?all_revisions=true").json()
        self.assertTrue(all_tasks["all_revisions"])
        self.assertEqual({task["object_id"] for task in all_tasks["tasks"]},
                         first_tasks | current_tasks)
        expected_all = document_tasks(self.store, head.object_id, all_revisions=True)
        self.assertEqual(all_tasks["tasks"], [
            project_task(task, self.container.handles).model_dump(mode="json")
            for task in expected_all])

        before = self.snapshot()
        retry = self.upload(workbook())
        self.assertTrue(retry["duplicate"])
        self.assertEqual(retry["event_id"], first["event_id"])
        self.status(retry, "processed")
        self.run_worker()
        self.assertEqual(self.snapshot(), before)
        unchanged_head, = self.heads()
        self.assertEqual(unchanged_head.digest(), next_head.digest())
        _, after_retry = self.assert_reads(unchanged_head)
        self.assertEqual(after_retry, current_tasks)
        self.assert_safe()

    def test_http_malformed_workbook_is_quarantined_by_real_worker(self):
        receipt = self.upload(b"not a workbook")
        self.status(receipt, "pending")
        self.assertEqual(self.heads(), ())
        self.run_worker()
        self.status(receipt, "quarantined")
        self.assertEqual(self.heads(), ())
        with self.store() as uow:
            self.assertEqual(uow.objects.by_kind("wbs_task"), ())
        self.assert_safe()
