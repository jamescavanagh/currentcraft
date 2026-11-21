"""Required HTTP boundary tests, synthetic stand-ins only."""

import asyncio
import hashlib
import io
import logging
from pathlib import Path
from tempfile import TemporaryDirectory
import threading
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from app.application.messaging.durable import PublishReceipt, inbox_key
from app.application.persistence.contracts import CommandRecord
from app.infrastructure.ingest.directory_blobs import DirectoryBlobStore
from app.infrastructure.ingest.intake_receipts import SqliteIntakeReceipts
from app.infrastructure.persistence import build_memory
from app.interfaces.http.app import create_app
from app.interfaces.http.container import Container
from app.interfaces.http.settings import Settings
from app.interfaces.http.routes import intake

TOKEN = "synthetic-shared-token"
SOURCE = "synthetic-private-source"


class Broker:
    def __init__(self):
        self.events = []
        self.fail = False
        self.confirmed = False

    async def publish(self, event):
        self.events.append(event)
        if self.fail:
            raise RuntimeError("synthetic-private-source /private/path synthetic-shared-token")
        await asyncio.sleep(0)
        self.confirmed = True
        return PublishReceipt(stream="DM_RAW", sequence=1, duplicate=len(self.events) > 1)


class HttpIntakeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.broker = Broker()
        self.factory = build_memory()
        self.blobs = DirectoryBlobStore(Path(self.tmp.name) / "blobs")
        self.receipts = SqliteIntakeReceipts(str(Path(self.tmp.name) / "receipts.sqlite3"))
        async def ok():
            return True
        async def close():
            pass
        settings = Settings("synthetic-dsn", ("nats://example.invalid",), "synthetic-nats", TOKEN)
        self.container = Container(settings, ok, ok, close, uow_factory=self.factory,
                                   intake_broker=self.broker, blobs=self.blobs, receipts=self.receipts)
        async def factory():
            return self.container
        self.client = self.enterContext(TestClient(create_app(factory), raise_server_exceptions=False))
        self.headers = {"Authorization": "Bearer " + TOKEN}

    def post(self, data=None, content=b"synthetic body", headers=None, files=None):
        return self.client.post("/v1/intake/documents",
                                data={"source_id": SOURCE, "format": "text", **(data or {})},
                                files=files or {"file": ("ignored-private-name.txt", content, "text/plain")},
                                headers=self.headers if headers is None else headers)

    def test_queued_receipt_is_allowlisted_and_publish_confirmed(self):
        response = self.post()
        self.assertEqual(response.status_code, 202, response.text)
        body = response.json()
        self.assertTrue(self.broker.confirmed)
        self.assertEqual(set(body), {"event_id", "stream", "sequence", "duplicate", "source_id",
                                     "content_sha256", "status_url", "detail"})
        self.assertNotIn(SOURCE, response.text)
        self.assertNotIn("ignored-private-name", response.text)
        self.assertNotIn("content_key", response.text)
        self.assertIn("not extracted", body["detail"])
        self.assertEqual(body["content_sha256"], hashlib.sha256(b"synthetic body").hexdigest())

    def test_auth_before_body_consumption_and_missing_token_fail_closed(self):
        app = self.client.app
        async def invoke(token):
            called = False
            messages = []
            async def receive():
                nonlocal called
                called = True
                raise AssertionError("unauthorized body consumed")
            async def send(message):
                messages.append(message)
            scope = {"type": "http", "asgi": {"version": "3.0"}, "http_version": "1.1", "method": "POST",
                     "scheme": "http", "path": "/v1/intake/documents", "raw_path": b"/v1/intake/documents",
                     "query_string": b"", "root_path": "", "headers": [(b"authorization", token.encode()),
                     (b"content-type", b"multipart/form-data; boundary=synthetic")],
                     "client": ("127.0.0.1", 1), "server": ("testserver", 80)}
            await app(scope, receive, send)
            return called, messages
        called, messages = asyncio.run(invoke("Bearer wrong"))
        self.assertFalse(called)
        self.assertEqual(messages[0]["status"], 401)
        object.__setattr__(self.container.settings, "api_token", "")
        called, messages = asyncio.run(invoke("Bearer " + TOKEN))
        self.assertFalse(called)
        self.assertEqual(messages[0]["status"], 503)

    def test_invalid_contracts_never_write_blobs(self):
        cases = [{"format": "pdf"}, {"source_id": "invalid/source"},
                 {"format": "xlsx"}, {"subject_ref": "demo"}, {"revision_label": "one"},
                 {"subject_kind": "person", "subject_namespace": "synthetic", "subject_ref": "demo", "document_type": "estimate"}]
        for values in cases:
            with self.subTest(values=values), patch.object(self.blobs, "put") as put:
                self.assertEqual(self.post(values).status_code, 422)
                put.assert_not_called()

    def test_xlsx_binding_and_explicit_revision_are_carried_not_inferred(self):
        fields = dict(format="xlsx", mapping="synthetic-profile", subject_kind="project",
                      subject_namespace="synthetic", subject_ref="demo", document_type="estimate", revision_label="one")
        self.assertEqual(self.post(fields).status_code, 202)
        raw = self.broker.events[-1]
        self.assertEqual(raw.payload["mapping"], "synthetic-profile")
        self.assertEqual(raw.payload["binding_revision_label"], "one")
        first_id = raw.event_id
        self.assertEqual(self.post({**fields, "revision_label": "two"}).status_code, 202)
        self.assertNotEqual(first_id, self.broker.events[-1].event_id)

    def test_retry_after_failed_publish_reuses_first_event_and_publishes_again(self):
        self.broker.fail = True
        self.assertEqual(self.post().status_code, 503)
        first = self.broker.events[0]
        self.broker.fail = False
        response = self.post()
        self.assertEqual(response.status_code, 202)
        self.assertEqual(self.broker.events[-1], first)
        again = self.post().json()
        self.assertEqual(again["event_id"], response.json()["event_id"])
        self.assertTrue(again["duplicate"])
        self.assertEqual(len(self.broker.events), 3)

    def test_file_limit_exact_boundary_ignores_content_length(self):
        with patch.object(intake, "FILE_LIMIT", 16):
            self.assertEqual(self.post(content=b"x" * 16).status_code, 202)
            with patch.object(self.blobs, "put") as put:
                response = self.post(content=b"x" * 17, headers={**self.headers, "Content-Length": "1"})
                self.assertEqual(response.status_code, 413, response.text)
                put.assert_not_called()

    def test_total_request_field_file_count_and_duplicate_bounds(self):
        with patch.object(intake, "REQUEST_LIMIT", 40):
            self.assertEqual(self.post().status_code, 413)
        self.assertEqual(self.post({"unknown": "value"}).status_code, 422)
        self.assertEqual(self.post({"mapping": "x" * 4097}).status_code, 422)
        files = [("file", ("one.txt", b"x")), ("file", ("two.txt", b"x"))]
        self.assertEqual(self.post(files=files).status_code, 422)
        files = [("file", ("one.txt", b"x")), ("source_id", (None, "other"))]
        self.assertEqual(self.post(files=files).status_code, 422)
        self.assertEqual(self.client.post("/v1/intake/documents", headers=self.headers, content=b"broken").status_code, 422)

    def test_blob_write_threadpool_and_failure_sanitization(self):
        ids = []
        actual = self.blobs.put
        def put(*args):
            ids.append(threading.get_ident())
            return actual(*args)
        loop_ids = []
        actual_publish = self.broker.publish
        async def publish(event):
            loop_ids.append(threading.get_ident())
            return await actual_publish(event)
        with patch.object(self.blobs, "put", side_effect=put), patch.object(self.broker, "publish", side_effect=publish):
            self.assertEqual(self.post().status_code, 202)
        self.assertNotEqual(ids[0], loop_ids[0])
        logs = io.StringIO()
        handler = logging.StreamHandler(logs)
        logging.getLogger().addHandler(handler)
        try:
            for target, method in [(self.blobs, "put"), (self.receipts, "select_first")]:
                with patch.object(target, method, side_effect=RuntimeError(SOURCE + " /private/path " + TOKEN)):
                    response = self.post()
                    self.assertEqual(response.status_code, 503)
                    self.assertNotIn(SOURCE, response.text)
            self.broker.fail = True
            self.assertEqual(self.post().status_code, 503)
        finally:
            logging.getLogger().removeHandler(handler)
        for secret in (SOURCE, TOKEN, "/private/path"):
            self.assertNotIn(secret, logs.getvalue())

    def test_handles_closed_on_success_and_validation_failure(self):
        original = intake._form
        forms = []
        async def capture(request):
            form = await original(request)
            forms.append(form)
            return form
        with patch.object(intake, "_form", side_effect=capture):
            self.assertEqual(self.post().status_code, 202)
            self.assertEqual(self.post({"format": "pdf"}).status_code, 422)
        self.assertTrue(all(form["file"].file.closed for form in forms))

    def test_status_uses_worker_inbox_key_and_never_claims_approval(self):
        response = self.post().json()
        url = response["status_url"]
        self.assertEqual(self.client.get(url, headers=self.headers).json()["status"], "pending")
        event = self.broker.events[-1]
        for outcome, status in [("applied", "processed"), ("rejected", "quarantined")]:
            # Separate fresh store for each outcome; no overwriting worker records.
            factory = build_memory()
            with factory() as uow:
                uow.commands.record(CommandRecord(command_id=inbox_key("ingest-v1", event.event_id),
                                                  command_type="broker.inbox", outcome=outcome,
                                                  recorded_at=event.occurred_at))
                uow.commit()
            self.container.uow_factory = factory
            result = self.client.get(url, headers=self.headers)
            self.assertEqual(result.json()["status"], status)
            self.assertIn("not approved work", result.json()["detail"])
        unknown = self.client.get("/v1/intake/intake_" + "0" * 32, headers=self.headers)
        self.assertEqual(unknown.json()["status"], "pending")
        self.assertEqual(self.client.get(url).status_code, 401)
        self.assertEqual(self.client.get("/v1/intake/not-a-handle", headers=self.headers).status_code, 422)

    def test_openapi_documents_both_routes_and_multipart_fields(self):
        schema = self.client.app.openapi()
        post = schema["paths"]["/v1/intake/documents"]["post"]
        fields = post["requestBody"]["content"]["multipart/form-data"]["schema"]["properties"]
        self.assertIn("file", fields)
        self.assertIn("revision_label", fields)
        self.assertTrue(post["security"])
        self.assertIn("/v1/intake/{event_id}", schema["paths"])

    def test_real_64_mib_boundary_and_oversize_stream_cleanup(self):
        from starlette.datastructures import Headers
        from fastapi import HTTPException
        import tempfile

        created = []
        real_spool = tempfile.SpooledTemporaryFile
        def spool(*args, **kwargs):
            result = real_spool(*args, **kwargs)
            created.append(result)
            return result

        async def parse(size):
            class StreamingRequest:
                headers = Headers({"content-type": "multipart/form-data; boundary=synthetic",
                                   "content-length": "1"})
                async def stream(self):
                    yield b'--synthetic\r\nContent-Disposition: form-data; name="file"; filename="demo"\r\n\r\n'
                    remaining = size
                    while remaining:
                        count = min(1024 * 1024, remaining)
                        yield b"x" * count
                        remaining -= count
                    yield b"\r\n--synthetic--\r\n"
            return await intake._form(StreamingRequest())

        with patch("starlette.formparsers.SpooledTemporaryFile", side_effect=spool):
            form = asyncio.run(parse(64 * 1024 * 1024))
            self.assertEqual(form["file"].size, 64 * 1024 * 1024)
            self.assertTrue(form["file"].file._rolled)
            asyncio.run(form.close())
            with self.assertRaises(HTTPException) as raised:
                asyncio.run(parse(64 * 1024 * 1024 + 1))
            self.assertEqual(raised.exception.status_code, 413)
        self.assertTrue(all(f.closed for f in created))

    def test_partial_multipart_header_bound_and_disconnect_close_spools(self):
        from starlette.datastructures import Headers
        from fastapi import HTTPException
        from starlette.requests import ClientDisconnect
        import tempfile
        created = []
        real_spool = tempfile.SpooledTemporaryFile
        def spool(*args, **kwargs):
            result = real_spool(*args, **kwargs)
            created.append(result)
            return result
        prefix = b'--synthetic\r\nContent-Disposition: form-data; name="file"; filename="demo"\r\n\r\n'
        async def parse(mode):
            class StreamingRequest:
                headers = Headers({"content-type": "multipart/form-data; boundary=synthetic"})
                async def stream(self):
                    yield prefix + b"body"
                    if mode == "disconnect":
                        raise ClientDisconnect()
                    if mode == "cancel":
                        raise asyncio.CancelledError()
            return await intake._form(StreamingRequest())
        with patch("starlette.formparsers.SpooledTemporaryFile", side_effect=spool):
            for mode, exception in [("truncated", HTTPException), ("disconnect", ClientDisconnect),
                                    ("cancel", asyncio.CancelledError)]:
                with self.subTest(mode=mode), self.assertRaises(exception):
                    asyncio.run(parse(mode))
        self.assertTrue(all(f.closed for f in created))
        boundary = "synthetic"
        body = (b"--synthetic\r\nContent-Disposition: form-data; name=\"file\"; filename=\"" +
                b"x" * (17 * 1024) + b"\"\r\n\r\nx\r\n--synthetic--\r\n")
        response = self.client.post("/v1/intake/documents", content=body,
                                    headers={**self.headers, "Content-Type": "multipart/form-data; boundary=" + boundary})
        self.assertEqual(response.status_code, 413)

    def test_concurrent_identical_http_submissions_select_one_event(self):
        from concurrent.futures import ThreadPoolExecutor
        with ThreadPoolExecutor(max_workers=6) as pool:
            responses = list(pool.map(lambda _: self.post(), range(12)))
        self.assertTrue(all(r.status_code == 202 for r in responses))
        self.assertEqual(len({r.json()["event_id"] for r in responses}), 1)
        self.assertEqual(len({e.event_id for e in self.broker.events}), 1)
        self.assertEqual(len(self.broker.events), 12)

    def test_invalid_broker_receipt_and_status_dependency_fail_safely(self):
        from unittest.mock import AsyncMock
        with patch.object(self.broker, "publish", new=AsyncMock(return_value=None)):
            self.assertEqual(self.post().status_code, 503)
        receipt = self.post().json()
        with patch.object(self.receipts, "get", side_effect=RuntimeError(SOURCE + " /private/path " + TOKEN)):
            response = self.client.get(receipt["status_url"], headers=self.headers)
            self.assertEqual(response.status_code, 503)
            for secret in (SOURCE, TOKEN, "/private/path"):
                self.assertNotIn(secret, response.text)

    def test_synthetic_post_worker_status_and_retry_are_not_restore(self):
        from app.infrastructure.messaging import InMemoryDurableBroker
        from app.infrastructure.ingest.wiring import build_durable_ingest
        from app.application.queries.documents import documents_for_reference
        from tests.test_durable_messaging import spec
        from tests.test_xlsx_workbook import CFG, PROFILE, BINDING, workbook

        broker = InMemoryDurableBroker()
        self.container.intake_broker = broker
        fields = dict(format="xlsx", mapping=PROFILE.name, **{
            "subject_kind": BINDING.subject_kind, "subject_namespace": BINDING.subject_namespace,
            "subject_ref": BINDING.subject_ref, "document_type": BINDING.document_type})
        first = self.post(fields, content=workbook())
        self.assertEqual(first.status_code, 202, first.text)
        first_receipt = first.json()
        self.assertEqual(self.client.get(first_receipt["status_url"], headers=self.headers).json()["status"], "pending")

        async def run_worker():
            worker = build_durable_ingest(broker=broker, uow_factory=self.factory, blobs=self.blobs,
                                          config=CFG, spec=spec(), profiles=(PROFILE,))
            await broker.ensure_consumer(worker.spec)
            await worker.run_batch()
        asyncio.run(run_worker())
        self.assertEqual(self.client.get(first_receipt["status_url"], headers=self.headers).json()["status"], "processed")

        second = self.post({**fields, "revision_label": "synthetic-two"}, content=workbook())
        self.assertEqual(second.status_code, 202)
        asyncio.run(run_worker())
        head = documents_for_reference(self.factory, BINDING.subject_kind,
                                       BINDING.subject_namespace, BINDING.subject_ref)[0]
        current = {r.target_id for r in head.relations if r.type == "current_revision"}
        retry = self.post(fields, content=workbook())
        self.assertEqual(retry.json()["event_id"], first_receipt["event_id"])
        self.assertTrue(retry.json()["duplicate"])
        asyncio.run(run_worker())
        same_head = documents_for_reference(self.factory, BINDING.subject_kind,
                                            BINDING.subject_namespace, BINDING.subject_ref)[0]
        self.assertEqual({r.target_id for r in same_head.relations if r.type == "current_revision"}, current)

        rejected = self.post({**fields, "source_id": "synthetic-rejected"}, content=b"not a workbook")
        self.assertEqual(rejected.status_code, 202)
        asyncio.run(run_worker())
        status = self.client.get(rejected.json()["status_url"], headers=self.headers)
        self.assertEqual(status.json()["status"], "quarantined")
