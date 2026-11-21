"""Read-route acceptance on synthetic memory records, not live DB evidence."""
from __future__ import annotations

import asyncio
from contextlib import contextmanager
import csv
import io
import logging
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from app.application.ingest.identity import subject_reference_id
from app.application.ingest.workbook_views import OUTLINE_COLUMNS
from app.application.persistence.services import persist_objects
from app.interfaces.http.app import create_app
from app.interfaces.http.container import Container
from app.interfaces.http.document_projection import project_document, project_outline, project_task
from app.interfaces.http.routes import documents as routes
from app.infrastructure.persistence import build_memory
from tests.test_http_api import _make_settings, SENTINEL_API_TOKEN
from tests.test_persistence import obj, T0

CANARY = "SYNTH-PRIVATE-READ-CANARY"
AUTH = {"Authorization": "Bearer " + SENTINEL_API_TOKEN}


class ReadRouteTests(unittest.TestCase):
    def setUp(self):
        self.store = build_memory()
        self.subject_id = subject_reference_id("project", "private.synthetic", CANARY)
        self.doc_id = "doc:" + CANARY
        self.head = obj(self.doc_id, kind="project_document", title=CANARY,
                        rels=[("current_revision", "rev:new"), ("document_of", self.subject_id)], profile=CANARY)
        self.current = obj("task:new", kind="wbs_task", title=CANARY, row=2, row_kind="task",
                           wbs_code="1.1", parent_wbs_code="1", wbs_level=1,
                           locator=CANARY, labor_sources=CANARY,
                           rels=[("extracted_from", self.doc_id), ("in_revision", "rev:new")])
        records = [self.head, self.current,
                   obj("task:old", kind="wbs_task", title=CANARY, row=1,
                       rels=[("extracted_from", self.doc_id), ("in_revision", "rev:old")]),
                   obj("phase:new", kind="phase_scope", title=CANARY, row=1, wbs_code="1", wbs_level=0,
                       rels=[("in_revision", "rev:new")]),
                   obj("task:other", kind="wbs_task", rels=[("extracted_from", "doc:other"), ("in_revision", "rev:other")]),
                   obj(self.subject_id, kind="project_reference", title=CANARY,
                       namespace="private.synthetic", reference=CANARY),
                   obj("wrong:kind", title=CANARY)]
        persist_objects(self.store, records, T0)
        self.read_calls = []
        self.writes = []
        outer = self

        class ReadOnlyObjects:
            def __getattr__(self, name):
                if name not in ("get", "by_kind", "related"):
                    outer.writes.append(name)
                    raise AssertionError("Write or unsupported access")
                def call(*args, **kwargs):
                    try:
                        asyncio.get_running_loop()
                    except RuntimeError:
                        pass
                    else:
                        raise AssertionError("Repository read ran on the event loop")
                    outer.read_calls.append(name)
                    with outer.store() as uow:
                        return getattr(uow.objects, name)(*args, **kwargs)
                return call

        def forbidden(*args, **kwargs):
            self.writes.append("commit")
            raise AssertionError("Read route attempted a write")

        @contextmanager
        def read_only():
            yield SimpleNamespace(objects=ReadOnlyObjects(), commit=forbidden)

        async def ready():
            return True

        async def close():
            pass

        self.container = Container(_make_settings(), ready, ready, close, uow_factory=read_only)
        self.handle = self.container.handles.encode("doc", self.doc_id)
        self.base = "/v1/documents/" + self.handle

        async def factory():
            return self.container
        self.app = create_app(factory)
        self.client = self.enterContext(TestClient(self.app, raise_server_exceptions=False))

    def assert_safe(self, response):
        for bad in (CANARY, self.doc_id, self.subject_id, "private.synthetic", SENTINEL_API_TOKEN):
            self.assertNotIn(bad, response.text)
            self.assertNotIn(bad, str(response.headers))

    def subject_path(self, kind="project"):
        return "/v1/subjects/" + kind + "/opaque/" + self.container.handles.encode("sub", self.subject_id) + "/documents"

    def test_all_routes_require_token_before_reading(self):
        for path in (self.base, self.base + "/tasks", self.base + "/wbs", self.subject_path()):
            for headers in ({}, {"Authorization": "Bearer wrong"}):
                response = self.client.get(path, headers=headers)
                self.assertEqual(response.status_code, 401)
                self.assert_safe(response)
        self.assertEqual(self.read_calls, [])

    def test_missing_configuration_and_dependency_fail_closed(self):
        self.container.settings = _make_settings(api_token="")
        response = self.client.get(self.base, headers=AUTH)
        self.assertEqual(response.status_code, 503)
        self.assertEqual(self.read_calls, [])
        self.container.settings = _make_settings()
        self.container.uow_factory = None
        response = self.client.get(self.base, headers=AUTH)
        self.assertEqual(response.status_code, 503)
        self.assert_safe(response)

    def test_head_matches_standalone_projection(self):
        response = self.client.get(self.base, headers=AUTH)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), project_document(self.head, self.container.handles).model_dump(mode="json"))
        self.assertEqual(response.headers["Cache-Control"], "no-store")
        self.assert_safe(response)
        self.assertTrue(self.read_calls)

    def test_current_and_explicit_all_revisions(self):
        response = self.client.get(self.base + "/tasks", headers=AUTH)
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.json()["all_revisions"])
        self.assertEqual(response.json()["tasks"], [project_task(self.current, self.container.handles).model_dump(mode="json")])
        response = self.client.get(self.base + "/tasks?all_revisions=true", headers=AUTH)
        self.assertEqual(response.status_code, 200)
        self.assertEqual({t["object_id"] for t in response.json()["tasks"]},
                         {self.container.handles.encode("task", t) for t in ("task:new", "task:old")})
        self.assertTrue(response.json()["all_revisions"])
        self.assert_safe(response)
        self.assertEqual(self.writes, [])

    def test_json_csv_parity_and_exact_header(self):
        response = self.client.get(self.base + "/wbs", headers=AUTH)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(tuple(response.json()["columns"]), OUTLINE_COLUMNS)
        rows = response.json()["rows"]
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[1]["parent_wbs_code"], rows[0]["wbs_code"])
        self.assert_safe(response)
        csv_response = self.client.get(self.base + "/wbs?format=csv", headers=AUTH)
        self.assertEqual(csv_response.status_code, 200)
        self.assertTrue(csv_response.headers["content-type"].startswith("text/csv"))
        self.assertEqual(csv_response.headers["cache-control"], "no-store")
        self.assert_safe(csv_response)
        rendered = list(csv.reader(io.StringIO(csv_response.text)))
        self.assertEqual(tuple(rendered[0]), OUTLINE_COLUMNS)
        self.assertEqual(rendered[1:], [["" if row[k] is None else str(row[k]) for k in OUTLINE_COLUMNS] for row in rows])
        self.assertEqual(self.writes, [])

    def test_subject_uses_private_descriptors_but_returns_only_projections(self):
        response = self.client.get(self.subject_path(), headers=AUTH)
        self.assertEqual(response.status_code, 200)
        self.assertEqual([d["object_id"] for d in response.json()["documents"]], [self.handle])
        self.assert_safe(response)
        link = self.client.get(self.base, headers=AUTH).json()["subjects"][0]
        self.assertEqual(link["reference"], self.container.handles.encode("sub", self.subject_id))
        self.assertEqual(self.writes, [])

    def test_unknown_raw_wrong_kind_and_restart_handles_are_safe_404(self):
        from app.interfaces.http.document_projection import HandleCodec
        for handle in ("unknown", self.doc_id, self.container.handles.encode("doc", "absent"),
                       self.container.handles.encode("doc", "wrong:kind"),
                       self.container.handles.encode("task", "task:new"), HandleCodec().encode("doc", self.doc_id)):
            for suffix in ("", "/tasks", "/wbs"):
                response = self.client.get("/v1/documents/" + handle + suffix, headers=AUTH)
                self.assertEqual(response.status_code, 404)
                self.assertEqual(response.json(), {"error": "not_found", "detail": "Resource not found."})
                self.assert_safe(response)

    def test_invalid_queries_and_raw_subject_inputs_are_safe(self):
        paths = [self.base + "/tasks?all_revisions=" + CANARY,
                 self.base + "/wbs?format=" + CANARY,
                 "/v1/subjects/person/opaque/" + self.container.handles.encode("sub", self.subject_id) + "/documents",
                 "/v1/subjects/project/private.synthetic/" + CANARY + "/documents"]
        for path in paths:
            response = self.client.get(path, headers=AUTH)
            self.assertEqual(response.status_code, 422)
            self.assert_safe(response)
        for path in (self.subject_path("opportunity"), "/v1/subjects/project/opaque/unknown/documents"):
            response = self.client.get(path, headers=AUTH)
            self.assertEqual(response.status_code, 404)
            self.assert_safe(response)

    def test_trailing_slashes_do_not_echo_raw_urls_in_redirects(self):
        response = self.client.get("/v1/documents/" + CANARY + "/", headers=AUTH, follow_redirects=False)
        self.assertEqual(response.status_code, 404)
        self.assertNotIn("location", response.headers)
        self.assert_safe(response)

    def test_empty_head_has_empty_tasks_and_outline(self):
        persist_objects(self.store, [obj(self.doc_id, kind="project_document", title=CANARY)], T0)
        for path, key in ((self.base + "/tasks", "tasks"), (self.base + "/wbs", "rows")):
            response = self.client.get(path, headers=AUTH)
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json()[key], [])
        csv_response = self.client.get(self.base + "/wbs?format=csv", headers=AUTH)
        self.assertEqual(len(list(csv.reader(io.StringIO(csv_response.text)))), 1)

    def test_integrity_errors_and_logs_never_include_path_or_exception(self):
        persist_objects(self.store, [obj(self.doc_id, kind="project_document", rels=[
            ("current_revision", "rev:old"), ("current_revision", "rev:new")])], T0)
        for suffix in ("/tasks", "/wbs"):
            with self.assertLogs("app.interfaces.http.errors", logging.ERROR) as captured:
                response = self.client.get(self.base + suffix + "?private=" + CANARY, headers=AUTH)
            self.assertEqual(response.status_code, 500)
            self.assert_safe(response)
            self.assertEqual(captured.output, ["ERROR:app.interfaces.http.errors:Unhandled internal HTTP error"])
            self.assertNotIn(self.handle, " ".join(captured.output))

    def test_driver_exception_text_type_and_traceback_are_not_logged(self):
        with patch.object(routes, "document_head", side_effect=RuntimeError(CANARY + "/private/path")):
            with self.assertLogs("app.interfaces.http.errors", logging.ERROR) as captured:
                response = self.client.get(self.base, headers=AUTH)
        self.assertEqual(response.status_code, 500)
        self.assert_safe(response)
        self.assertEqual(captured.output, ["ERROR:app.interfaces.http.errors:Unhandled internal HTTP error"])
        self.assertIsNone(captured.records[0].exc_info)

    def test_lookup_ceiling_fails_closed_without_incomplete_not_found(self):
        with patch.object(routes, "LOOKUP_LIMIT", 0):
            response = self.client.get(self.base, headers=AUTH)
        self.assertEqual(response.status_code, 503)
        self.assert_safe(response)

    def test_corrupt_stored_subject_cannot_select_another_reference(self):
        persist_objects(self.store, [obj(self.subject_id, kind="project_reference", namespace="other", reference="other")], T0)
        with self.assertLogs("app.interfaces.http.errors", logging.ERROR):
            response = self.client.get(self.subject_path(), headers=AUTH)
        self.assertEqual(response.status_code, 500)
        self.assert_safe(response)

    def test_no_write_methods_available_on_read_path(self):
        for path in (self.base, self.base + "/tasks", self.base + "/tasks?all_revisions=true", self.base + "/wbs?format=csv", self.subject_path()):
            self.assertEqual(self.client.get(path, headers=AUTH).status_code, 200)
        self.assertTrue(self.read_calls)
        self.assertEqual(self.writes, [])
        for verb in ("post", "put", "patch", "delete"):
            self.assertEqual(getattr(self.client, verb)(self.base, headers=AUTH).status_code, 405)

    def test_openapi_has_all_read_routes_security_and_formats(self):
        schema = self.app.openapi()
        self.assertNotIn(CANARY, str(schema))
        for path in ("/v1/documents/{document_id}", "/v1/documents/{document_id}/tasks",
                     "/v1/documents/{document_id}/wbs", "/v1/subjects/{subject_kind}/{namespace}/{reference}/documents"):
            route = schema["paths"][path]["get"]
            self.assertTrue(route["security"])
            self.assertEqual(set(schema["paths"][path]), {"get"})
        content = schema["paths"]["/v1/documents/{document_id}/wbs"]["get"]["responses"]["200"]["content"]
        self.assertIn("application/json", content)
        self.assertIn("text/csv", content)


class WorkbookReadRouteTests(unittest.TestCase):
    def test_synthetic_worker_to_read_routes(self):
        import tempfile
        from app.application.ingest.contracts import RawItem
        from app.application.ingest.services import raw_item_event
        from app.application.queries.documents import document_tasks, document_outline, documents_for_reference
        from app.infrastructure.ingest.directory_blobs import DirectoryBlobStore
        from app.infrastructure.ingest.wiring import build_durable_ingest
        from app.infrastructure.messaging import InMemoryDurableBroker
        from tests.test_durable_messaging import spec
        from tests.test_xlsx_workbook import BINDING, CFG, PROFILE, workbook

        store = build_memory()
        with tempfile.TemporaryDirectory() as directory:
            async def ingest():
                broker, blobs = InMemoryDurableBroker(), DirectoryBlobStore(directory)
                reference = blobs.put(workbook(), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
                raw = RawItem(platform="file", format="xlsx", source_id="synthetic-http-read", received_at=T0,
                              content=reference, mapping=PROFILE.name, binding=BINDING)
                worker = build_durable_ingest(broker=broker, uow_factory=store, blobs=blobs,
                                              config=CFG, spec=spec(), profiles=(PROFILE,))
                await broker.ensure_consumer(worker.spec)
                await broker.publish(raw_item_event(raw))
                await worker.run_batch()
            asyncio.run(ingest())
        head = documents_for_reference(store, BINDING.subject_kind, BINDING.subject_namespace, BINDING.subject_ref)[0]
        async def ready(): return True
        async def close(): pass
        container = Container(_make_settings(), ready, ready, close, uow_factory=store)
        async def factory(): return container
        handle = container.handles.encode("doc", head.object_id)
        with TestClient(create_app(factory)) as client:
            tasks = client.get("/v1/documents/" + handle + "/tasks", headers=AUTH)
            self.assertEqual(tasks.status_code, 200)
            self.assertEqual(tasks.json()["tasks"], [project_task(t, container.handles).model_dump(mode="json")
                                                    for t in document_tasks(store, head.object_id)])
            outline = client.get("/v1/documents/" + handle + "/wbs", headers=AUTH)
            self.assertEqual(outline.status_code, 200)
            expected = project_outline(document_outline(store, head.object_id), head.object_id, container.handles)
            self.assertEqual(outline.json()["rows"], [r.model_dump(mode="json") for r in expected])
            for canary in (BINDING.subject_ref, BINDING.subject_namespace, PROFILE.name, "Grid!", "Site walk", "SW-1"):
                self.assertNotIn(canary, tasks.text + outline.text)


class ReadWiringTests(unittest.IsolatedAsyncioTestCase):
    async def test_composition_root_supplies_existing_repository_factory(self):
        from app.interfaces.http import wiring
        store = build_memory()
        class Broker:
            is_connected = True
            async def close(self): pass
        async def connect(**kwargs): return Broker()
        with patch.object(wiring, "build_postgres", return_value=store), \
             patch.object(wiring, "connect_jetstream", side_effect=connect):
            container = await wiring.build_container(_make_settings())
        self.assertIs(container.uow_factory, store)
        self.assertTrue(await container.database_ready())
        await container.close()
