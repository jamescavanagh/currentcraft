"""Internal query contracts. Stand-ins are not live PostgreSQL evidence."""
import ast
import hashlib
import importlib.util
import sys
import unittest
from contextlib import contextmanager
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from pydantic import ValidationError
from app.application.ingest.identity import subject_reference_id
from app.application.messaging.durable import (
    TransactionalWorker, _inbox_key, inbox_key,
)
from app.application.persistence.contracts import CommandRecord
from app.application.persistence.services import persist_objects, tasks_of
from app.application.queries.documents import (
    document_head, document_outline, document_tasks, documents_for_reference,
    intake_status,
)
from app.infrastructure.persistence import build_duckdb_standin, build_memory
from app.infrastructure.ingest.wiring import build_durable_ingest
from app.infrastructure.ingest.directory_blobs import DirectoryBlobStore
from app.infrastructure.messaging import InMemoryDurableBroker
from app.application.ingest.contracts import RawItem
from app.application.ingest.services import raw_item_event
from tests.test_persistence import T0, obj
from tests.test_durable_messaging import event, spec
from tests.test_xlsx_workbook import BINDING, CFG, PROFILE, workbook
import tempfile


class QueryContract:
    def setUp(self):
        self.store = self.make()
        self.commits = 0

        @contextmanager
        def read_only():
            with self.store() as uow:
                def forbidden():
                    self.commits += 1
                    raise AssertionError("query committed")
                uow.commit = forbidden
                yield uow
        self.read = read_only
        subject = subject_reference_id("project", "example", "SYNTH-1")
        persist_objects(self.store, [
            obj("doc:1", kind="project_document", rels=[
                ("current_revision", "rev:2"), ("document_of", subject)]),
            obj("task:old", kind="wbs_task", title="Old", rels=[
                ("extracted_from", "doc:1"), ("in_revision", "rev:1")], row=1),
            obj("task:new", kind="wbs_task", title="New", rels=[
                ("extracted_from", "doc:1"), ("in_revision", "rev:2")], row=2),
            obj("phase:new", kind="phase_scope", title="Phase", rels=[
                ("in_revision", "rev:2")], row=1),
            obj("other:task", kind="wbs_task", rels=[
                ("extracted_from", "doc:other"), ("in_revision", "rev:other")]),
            obj("wrong:kind"),
        ], T0)

    def test_head_and_wrong_kind(self):
        self.assertEqual(document_head(self.read, "doc:1").kind, "project_document")
        self.assertIsNone(document_head(self.read, "missing"))
        self.assertIsNone(document_head(self.read, "wrong:kind"))

    def test_current_tasks_match_existing_query(self):
        got = document_tasks(self.read, "doc:1")
        self.assertEqual([x.object_id for x in got], ["task:new"])
        self.assertEqual(got, tasks_of(self.read, "doc:1"))

    def test_all_revisions_do_not_include_other_documents(self):
        self.assertEqual({x.object_id for x in document_tasks(self.read, "doc:1", True)},
                         {"task:new", "task:old"})

    def test_unknown_and_wrong_kind_are_distinct_from_empty(self):
        for key in ("missing", "wrong:kind"):
            self.assertIsNone(document_tasks(self.read, key))
            self.assertIsNone(document_tasks(self.read, key, True))
            self.assertIsNone(document_outline(self.read, key))

    def test_outline_selects_current_revision_and_sheet_order(self):
        rows = document_outline(self.read, "doc:1")
        self.assertEqual([r["name"] for r in rows], ["Phase", "New"])
        self.assertEqual(rows[0]["row_kind"], "phase")

    def test_no_current_revision_is_empty(self):
        persist_objects(self.store, [obj("doc:empty", kind="project_document")], T0)
        self.assertEqual(document_tasks(self.read, "doc:empty"), ())
        self.assertEqual(document_outline(self.read, "doc:empty"), [])

    def test_multiple_current_revisions_fail_closed(self):
        persist_objects(self.store, [obj("doc:bad", kind="project_document", rels=[
            ("current_revision", "rev:1"), ("current_revision", "rev:2")])], T0)
        for query in (document_tasks, document_outline):
            with self.assertRaisesRegex(ValueError, "multiple current revisions"):
                query(self.read, "doc:bad")

    def test_subject_lookup_and_validation(self):
        self.assertEqual([x.object_id for x in documents_for_reference(
            self.read, "project", "example", "SYNTH-1")], ["doc:1"])
        self.assertEqual(documents_for_reference(
            self.read, "opportunity", "example", "SYNTH-1"), ())
        with self.assertRaises(ValidationError):
            documents_for_reference(self.read, "person", "example", "SYNTH-1")

    def test_status_is_stored_outcome_and_handler_scoped(self):
        key = "a" * 64
        self.assertEqual(intake_status(self.read, "ingest-v1", key), "pending")
        for handler, outcome, expected in (
            ("applied-handler", "applied", "processed"),
            ("rejected-handler", "rejected", "quarantined"),
        ):
            with self.store() as uow:
                uow.commands.record(CommandRecord(
                    command_id=inbox_key(handler, key), command_type="broker.inbox",
                    recorded_at=T0, outcome=outcome))
                uow.commit()
            self.assertEqual(intake_status(self.read, handler, key), expected)
        self.assertEqual(intake_status(self.read, "ingest-v1", key), "pending")

    def test_queries_never_commit(self):
        document_head(self.read, "doc:1")
        document_tasks(self.read, "doc:1")
        document_tasks(self.read, "doc:1", True)
        document_outline(self.read, "doc:1")
        intake_status(self.read, "ingest-v1", "b" * 64)
        documents_for_reference(self.read, "project", "example", "SYNTH-1")
        self.assertEqual(self.commits, 0)


class MemoryQueries(QueryContract, unittest.TestCase):
    make = staticmethod(build_memory)


@unittest.skipUnless(importlib.util.find_spec("duckdb"), "DuckDB stand-in not installed")
class DuckDBQueries(QueryContract, unittest.TestCase):
    make = staticmethod(build_duckdb_standin)


class QueryBoundaries(unittest.TestCase):
    def test_inbox_key_preserves_formula_and_legacy_alias(self):
        expected = "inbox:" + hashlib.sha256(b"handler:message").hexdigest()
        self.assertEqual(inbox_key("handler", "message"), expected)
        self.assertIs(inbox_key, _inbox_key)

    def test_queries_have_no_framework_or_driver_imports(self):
        forbidden = ("fastapi", "starlette", "uvicorn", "numpy", "torch",
                     "psycopg", "duckdb", "nats", "app.infrastructure", "app.interfaces")
        for path in (ROOT / "src/app/application/queries").glob("*.py"):
            for node in ast.walk(ast.parse(path.read_text())):
                names = ([n.name for n in node.names] if isinstance(node, ast.Import)
                         else [node.module or ""] if isinstance(node, ast.ImportFrom) else [])
                for name in names:
                    self.assertFalse(any(name == f or name.startswith(f + ".")
                                         for f in forbidden), (path, name))


class WorkerStatusQueries(unittest.IsolatedAsyncioTestCase):
    async def test_actual_worker_markers_match_status_queries(self):
        broker, store = InMemoryDurableBroker(), build_memory()
        consumer = spec()
        await broker.ensure_consumer(consumer)
        worker = TransactionalWorker(broker, store, consumer, "query-test", lambda u, e: None)
        envelope = event("query")
        await broker.publish(envelope)
        self.assertEqual(intake_status(store, "query-test", envelope.event_id), "pending")
        await worker.run_batch()
        self.assertEqual(intake_status(store, "query-test", envelope.event_id), "processed")
        self.assertEqual(intake_status(store, "other-handler", envelope.event_id), "pending")

    async def test_exhausted_worker_failure_is_quarantined(self):
        broker, store = InMemoryDurableBroker(), build_memory()
        consumer = spec()
        await broker.ensure_consumer(consumer)
        def fail(uow, envelope):
            raise RuntimeError("synthetic failure")
        worker = TransactionalWorker(broker, store, consumer, "failure-test", fail, max_attempts=1)
        envelope = event("failure")
        await broker.publish(envelope)
        await worker.run_batch()
        self.assertEqual(intake_status(store, "failure-test", envelope.event_id), "quarantined")

    async def test_synthetic_workbook_query_pipeline(self):
        with tempfile.TemporaryDirectory() as directory:
            broker, store = InMemoryDurableBroker(), build_memory()
            blobs = DirectoryBlobStore(directory)
            reference = blobs.put(workbook(), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
            raw = RawItem(platform="file", format="xlsx", source_id="synthetic-query",
                          received_at=T0, content=reference, mapping=PROFILE.name, binding=BINDING)
            envelope = raw_item_event(raw)
            worker = build_durable_ingest(
                broker=broker, uow_factory=store, blobs=blobs, config=CFG,
                spec=spec(), profiles=(PROFILE,))
            await broker.ensure_consumer(worker.spec)
            await broker.publish(envelope)
            await worker.run_batch()
            documents = documents_for_reference(
                store, BINDING.subject_kind, BINDING.subject_namespace, BINDING.subject_ref)
            self.assertEqual(len(documents), 1)
            doc = documents[0]
            self.assertEqual(document_tasks(store, doc.object_id), tasks_of(store, doc.object_id))
            self.assertTrue(document_outline(store, doc.object_id))
            self.assertEqual(intake_status(store, worker.handler_id, envelope.event_id), "processed")
