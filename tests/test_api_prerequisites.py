"""API prerequisite regressions, synthetic fixtures and stand-ins only.

Design: docs/architecture/API_PREREQUISITES.md. No live services required.
"""
import hashlib
import importlib.util
import sys
import tempfile
import types
import unittest
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

from app.application.ingest.contracts import RawItem
from app.application.ingest.durable import DurableIngestHandler
from app.application.ingest.identity import document_id, subject_reference_id
from app.application.ingest.services import raw_item_event
from app.application.messaging.durable import TransactionalWorker, inbox_key
from app.application.queries.documents import intake_status
from app.infrastructure.ingest.directory_blobs import DirectoryBlobStore
from app.infrastructure.ingest.wiring import build_durable_ingest
from app.infrastructure.messaging import InMemoryDurableBroker
from app.infrastructure.messaging.jetstream import connect_jetstream
from app.infrastructure.persistence import build_memory
from tests.test_durable_messaging import event, spec
from tests.test_xlsx_workbook import BINDING, CFG, PROFILE, WHEN, run, workbook

ROOT = Path(__file__).resolve().parents[1]


def legacy_key(*parts):
    return hashlib.sha256("|".join(parts).encode()).hexdigest()[:20]


class WorkbookIdentityRegression(unittest.TestCase):
    def test_whole_fixture_serialization_matches_legacy_formulas(self):
        for binding in (BINDING, None):
            for data in (workbook(), workbook(Side={"A1": "changed synthetic annotation", "B2": 6})):
                with self.subTest(bound=binding is not None, digest=hashlib.sha256(data).hexdigest()):
                    _, raw, actual = run(data, binding=binding)
                    with patch("app.infrastructure.ingest.xlsx.document_id",
                               side_effect=lambda p, s: f"{p}:xlsx:project_document:{legacy_key(p, s)}") as doc, patch(
                            "app.infrastructure.ingest.xlsx.subject_reference_id",
                            side_effect=lambda k, n, r: f"ref:{k}:{legacy_key(n, r)}") as subject:
                        _, _, old = run(data, binding=binding)
                    self.assertIsNone(actual.rejection)
                    self.assertTrue(actual.objects)
                    self.assertEqual([o.model_dump_json() for o in actual.objects],
                                     [o.model_dump_json() for o in old.objects])
                    doc.assert_called_once_with(raw.platform, raw.source_id)
                    if binding:
                        subject.assert_called_once_with(binding.subject_kind, binding.subject_namespace,
                                                        binding.subject_ref)
                    else:
                        subject.assert_not_called()
                    head, = [o for o in actual.objects if o.kind == "project_document"]
                    self.assertEqual(head.object_id, document_id(raw.platform, raw.source_id))
                    if binding:
                        self.assertIn(subject_reference_id(binding.subject_kind, binding.subject_namespace,
                                                           binding.subject_ref),
                                      [r.target_id for r in head.relations if r.type == "document_of"])


class QuarantineStatus(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.blobs = DirectoryBlobStore(self.temp.name)
        self.broker, self.store = InMemoryDurableBroker(), build_memory()
        self.consumer = spec()
        await self.broker.ensure_consumer(self.consumer)
        self.worker = build_durable_ingest(broker=self.broker, uow_factory=self.store, blobs=self.blobs,
                                          config=CFG, spec=self.consumer, profiles=(PROFILE,), retry_delay=0)

    def raw(self, data=b"not a workbook", mapping=PROFILE.name):
        return RawItem(platform="file", format="xlsx", source_id="synthetic-prerequisite", received_at=WHEN,
                       content=self.blobs.put(data, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"),
                       mapping=mapping, binding=BINDING)

    async def rejected(self, raw):
        envelope = raw_item_event(raw)
        await self.broker.publish(envelope)
        self.assertEqual(intake_status(self.store, self.worker.handler_id, envelope.event_id), "pending")
        await self.worker.run_batch()
        self.assertEqual(intake_status(self.store, self.worker.handler_id, envelope.event_id), "quarantined")
        with self.store() as u:
            record = u.commands.get(inbox_key(self.worker.handler_id, envelope.event_id))
            self.assertEqual(record.outcome, "rejected")
            q, = u.outbox.pending()
            self.assertEqual(q.envelope["kind"], "ingest.rejection")
            self.assertEqual(q.envelope["causation_id"], envelope.event_id)
            self.assertEqual(u.objects.by_kind("project_document"), ())
        self.assertEqual(await self.worker.run_batch(), 0)
        return envelope

    async def test_malformed_workbook_is_quarantined(self):
        await self.rejected(self.raw())

    async def test_unknown_profile_is_quarantined(self):
        await self.rejected(self.raw(workbook(), mapping="unknown-synthetic-profile"))

    async def test_unknown_adapter_is_quarantined(self):
        self.worker.handler = DurableIngestHandler(self.blobs, {}, CFG)
        await self.rejected(self.raw())

    async def test_successful_workbook_is_processed(self):
        envelope = raw_item_event(self.raw(workbook()))
        await self.broker.publish(envelope)
        await self.worker.run_batch()
        self.assertEqual(intake_status(self.store, self.worker.handler_id, envelope.event_id), "processed")
        with self.store() as u:
            self.assertTrue(u.objects.by_kind("project_document"))
            self.assertTrue(all(e.envelope["kind"] == "domain.stored" for e in u.outbox.pending()))

    async def test_rejected_marker_and_event_committed_before_ack(self):
        envelope = raw_item_event(self.raw())
        original = self.broker.ack
        async def verify(delivery):
            self.assertEqual(intake_status(self.store, self.worker.handler_id, envelope.event_id), "quarantined")
            with self.store() as u:
                self.assertEqual(len(u.outbox.pending()), 1)
            await original(delivery)
        self.broker.ack = verify
        await self.broker.publish(envelope)
        await self.worker.run_batch()

    async def test_lost_ack_replay_does_not_repeat_rejection(self):
        envelope = raw_item_event(self.raw())
        await self.broker.publish(envelope)
        original = self.broker.ack
        self.broker.ack = AsyncMock(side_effect=ConnectionError("synthetic lost ack"))
        with self.assertRaises(ConnectionError):
            await self.worker.run_batch()
        self.broker.ack = original
        self.broker.advance(2)
        with patch.object(self.worker, "handler", side_effect=AssertionError("handler replayed")):
            await self.worker.run_batch()
        self.assertEqual(intake_status(self.store, self.worker.handler_id, envelope.event_id), "quarantined")
        with self.store() as u:
            self.assertEqual(len(u.outbox.pending()), 1)

    async def test_commit_failure_rolls_back_rejection_and_never_acks(self):
        envelope = raw_item_event(self.raw())
        @contextmanager
        def broken():
            with self.store() as u:
                u.commit = MagicMock(side_effect=ConnectionError("synthetic commit failure"))
                yield u
        self.worker.uow_factory = broken
        self.worker.max_attempts = 1
        self.broker.ack = AsyncMock()
        await self.broker.publish(envelope)
        with self.assertRaises(ConnectionError):
            await self.worker.run_batch()
        self.broker.ack.assert_not_awaited()
        self.assertEqual(intake_status(self.store, self.worker.handler_id, envelope.event_id), "pending")
        with self.store() as u:
            self.assertEqual(u.outbox.pending(), ())

    async def test_legacy_none_handler_is_successful(self):
        self.worker.handler = lambda u, e: None
        envelope = event("legacy-none")
        await self.broker.publish(envelope)
        await self.worker.run_batch()
        self.assertEqual(intake_status(self.store, self.worker.handler_id, envelope.event_id), "processed")

    async def test_invalid_handler_outcome_retries_without_marker(self):
        self.worker.handler = lambda u, e: "unexpected-synthetic-value"
        envelope = event("invalid-outcome")
        await self.broker.publish(envelope)
        self.broker.retry = AsyncMock(wraps=self.broker.retry)
        await self.worker.run_batch()
        self.broker.retry.assert_awaited_once()
        self.assertEqual(intake_status(self.store, self.worker.handler_id, envelope.event_id), "pending")


class ConnectionPolicy(unittest.IsolatedAsyncioTestCase):
    async def test_default_connection_policy_unchanged(self):
        fake = types.ModuleType("nats")
        fake.connect = AsyncMock(return_value=MagicMock())
        with patch.dict(sys.modules, {"nats": fake}):
            await connect_jetstream()
        self.assertEqual(fake.connect.call_args.kwargs,
                         {"servers": ["nats://127.0.0.1:4222"], "allow_reconnect": True,
                          "max_reconnect_attempts": 10})

    async def test_runtime_overrides_forwarded_with_token(self):
        fake = types.ModuleType("nats")
        fake.connect = AsyncMock(return_value=MagicMock())
        with patch.dict(sys.modules, {"nats": fake}):
            await connect_jetstream(("nats://nats:4222",), token="synthetic-token",
                                    connect_timeout=2, max_reconnect_attempts=2)
        self.assertEqual(fake.connect.call_args.kwargs,
                         {"servers": ["nats://nats:4222"], "allow_reconnect": True, "token": "synthetic-token",
                          "connect_timeout": 2, "max_reconnect_attempts": 2})

    def runtime(self):
        module_spec = importlib.util.spec_from_file_location("prerequisite_runtime", ROOT / "deploy/local/runtime.py")
        runtime = importlib.util.module_from_spec(module_spec)
        module_spec.loader.exec_module(runtime)
        return runtime

    async def test_runtime_uses_shared_helper(self):
        runtime = self.runtime()
        fake = types.ModuleType("nats")
        fake.errors = types.SimpleNamespace(Error=type("SyntheticNatsError", (Exception,), {}))
        sentinel = object()
        with patch.dict(sys.modules, {"nats": fake}), patch.object(runtime, "secret", return_value="synthetic-token"), patch.object(
                runtime, "connect_jetstream", AsyncMock(return_value=sentinel)) as connect:
            self.assertIs(await runtime.broker(), sentinel)
        connect.assert_awaited_once_with(("nats://nats:4222",), token="synthetic-token", connect_timeout=2,
                                        max_reconnect_attempts=2)

    async def test_runtime_exhausts_bounded_startup_retries_safely(self):
        runtime = self.runtime()
        fake = types.ModuleType("nats")
        error = type("SyntheticNatsError", (Exception,), {})
        fake.errors = types.SimpleNamespace(Error=error)
        for failure in (OSError("synthetic-sensitive-detail"), error("synthetic-sensitive-detail")):
            with self.subTest(error=type(failure).__name__), patch.dict(sys.modules, {"nats": fake}), patch.object(
                    runtime, "secret", return_value="synthetic-token"), patch.object(
                    runtime, "connect_jetstream", AsyncMock(side_effect=failure)) as connect, patch.object(
                    runtime.asyncio, "sleep", AsyncMock()) as sleep:
                with self.assertRaisesRegex(RuntimeError, "local broker not ready") as raised:
                    await runtime.broker()
                self.assertNotIn("synthetic-sensitive-detail", str(raised.exception))
                self.assertEqual(connect.await_count, 60)
                self.assertEqual(sleep.await_count, 59)
                self.assertTrue(all(c.args == (1,) for c in sleep.call_args_list))


if __name__ == "__main__":
    unittest.main()
