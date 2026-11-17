"""Durable port, transaction boundaries and real-server gate (NATS_URL + nats-py required)."""
import asyncio
import importlib.util
import os
import sys
import tempfile
import types
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import AsyncMock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from app.application.messaging.contracts import make_event
from app.application.messaging.durable import DurableConsumerSpec, TransactionalWorker, relay_durable_outbox
from app.application.ingest.services import raw_item_event
from app.infrastructure.messaging import InMemoryDurableBroker, JetStreamBroker, connect_jetstream
from app.infrastructure.messaging.subjects import topic_to_subject, subject_to_topic, pattern_to_subjects
from app.infrastructure.persistence import build_memory
from app.infrastructure.ingest.directory_blobs import DirectoryBlobStore
from app.infrastructure.ingest.wiring import build_durable_ingest
from app.application.ingest.contracts import RawItem
from tests.test_persistence import obj
from tests.test_xlsx_workbook import CFG, PROFILE, BINDING, workbook, by

WHEN = datetime(2026, 11, 12, 20, 0, tzinfo=timezone.utc)


def event(i='1'):
    return make_event(topic='raw/file/text/' + i, kind='raw.item', source='test', epistemic_status='computed',
                      occurred_at=WHEN, payload={'test': i})


def spec(name='ingest'):
    return DurableConsumerSpec(stream='DM_RAW', durable=name, pattern='raw/#', batch_size=2, max_ack_pending=4, ack_wait=1)


class Subjects(unittest.TestCase):
    def test_reversible_and_collision_free(self):
        topics = ['raw/share.point/xlsx/file:1', 'raw/share/point/xlsx/file:1', 'raw', 'raw/file/text/a_b-c']
        subjects = [topic_to_subject(t) for t in topics]
        self.assertEqual(len(set(subjects)), len(topics))
        for t, s in zip(topics, subjects):
            self.assertEqual(subject_to_topic(s), t)
        self.assertEqual(topic_to_subject('raw/a.b').count('.'), 2)

    def test_wildcards_and_parent_semantics(self):
        parent, children = pattern_to_subjects('raw/#')
        self.assertEqual(parent, topic_to_subject('raw'))
        self.assertEqual(children, parent + '.>')
        self.assertIn('.*.', pattern_to_subjects('raw/+/xlsx')[0])
        for bad in ['#', 'raw/#/bad', 'raw/a*']:
            with self.assertRaises(ValueError):
                pattern_to_subjects(bad)
        for bad in ['other.t61', 'dm.tzz', 'dm.t6A', 'dm.t612f62']:
            with self.assertRaises(ValueError):
                subject_to_topic(bad)

    def test_consumer_limits(self):
        with self.assertRaises(ValueError):
            spec().model_validate({**spec().model_dump(), 'batch_size': 10, 'max_ack_pending': 1})


class DurableBehavior(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.broker = InMemoryDurableBroker()
        self.uow = build_memory()
        self.spec = spec()
        await self.broker.ensure_consumer(self.spec)

    async def test_confirm_dedup_and_independent_consumers(self):
        a = await self.broker.publish(event())
        b = await self.broker.publish(event())
        self.assertFalse(a.duplicate)
        self.assertTrue(b.duplicate)
        await self.broker.ensure_consumer(spec('index'))
        d, = await self.broker.fetch('ingest', 1)
        await self.broker.ack(d)
        self.assertEqual(await self.broker.fetch('ingest', 1), ())
        self.assertEqual(len(await self.broker.fetch('index', 1)), 1)

    async def test_pending_expiry_and_delayed_retry(self):
        await self.broker.publish(event())
        d, = await self.broker.fetch('ingest', 1)
        self.assertEqual(await self.broker.fetch('ingest', 1), ())
        self.broker.advance(2)
        d, = await self.broker.fetch('ingest', 1)
        self.assertEqual(d.attempt, 2)
        await self.broker.retry(d, 4)
        self.assertEqual(await self.broker.fetch('ingest', 1), ())
        self.broker.advance(4)
        d, = await self.broker.fetch('ingest', 1)
        self.assertEqual(d.attempt, 3)

    async def test_commit_precedes_ack_and_replay_inbox_deduplicates(self):
        calls = []
        def handler(u, e):
            calls.append(e.event_id)
            u.objects.put(obj('committed'))
        worker = TransactionalWorker(self.broker, self.uow, self.spec, 'test-handler', handler)
        await self.broker.publish(event())
        d, = await self.broker.fetch('ingest', 1)
        original_ack = self.broker.ack
        async def check_ack(delivery):
            with self.uow() as u:
                self.assertIsNotNone(u.objects.get('committed'))
            raise ConnectionError('lost ack')
        self.broker.ack = check_ack
        with self.assertRaises(ConnectionError):
            await worker.process(d)
        self.broker.ack = original_ack
        self.broker.advance(2)
        d, = await self.broker.fetch('ingest', 1)
        await worker.process(d)
        self.assertEqual(len(calls), 1)

    async def test_rollback_retry_then_quarantine_commit_before_ack(self):
        def fail(u, e):
            u.objects.put(obj('rolled-back'))
            raise RuntimeError('secret detail must not leak')
        worker = TransactionalWorker(self.broker, self.uow, self.spec, 'broken', fail, max_attempts=2, retry_delay=0)
        await self.broker.publish(event())
        await worker.run_batch()
        with self.uow() as u:
            self.assertIsNone(u.objects.get('rolled-back'))
            self.assertEqual(u.outbox.pending(), ())
        await worker.run_batch()
        with self.uow() as u:
            self.assertIsNone(u.objects.get('rolled-back'))
            q, = u.outbox.pending()
        self.assertEqual(q.envelope['kind'], 'ingest.rejection')
        self.assertNotIn('secret detail', str(q.envelope))
        self.assertEqual(await self.broker.fetch('ingest', 1), ())

    async def test_outbox_publish_failure_never_marks_sent(self):
        with self.uow() as u:
            u.outbox.add(event(), WHEN)
            u.commit()
        original = self.broker.publish
        self.broker.publish = AsyncMock(side_effect=ConnectionError('broker unavailable'))
        with self.assertRaises(ConnectionError):
            await relay_durable_outbox(self.uow, self.broker, WHEN)
        with self.uow() as u:
            self.assertEqual(len(u.outbox.pending()), 1)
        self.broker.publish = original
        self.assertEqual(await relay_durable_outbox(self.uow, self.broker, WHEN), 1)
        with self.uow() as u:
            self.assertEqual(u.outbox.pending(), ())

    async def test_independent_projection_generation_can_reprocess(self):
        calls = []
        await self.broker.publish(event())
        w = TransactionalWorker(self.broker, self.uow, self.spec, 'generation-1', lambda u, e: calls.append(1))
        await w.run_batch()
        newer = spec('rebuild')
        await self.broker.ensure_consumer(newer)
        w = TransactionalWorker(self.broker, self.uow, newer, 'generation-2', lambda u, e: calls.append(2))
        await w.run_batch()
        self.assertEqual(calls, [1, 2])

    async def test_same_handler_id_deduplicates_across_replay_consumers(self):
        calls = []
        await self.broker.publish(event())
        first = TransactionalWorker(self.broker, self.uow, self.spec, 'stable-handler', lambda u, e: calls.append(1))
        await first.run_batch()
        another = spec('replay-same-handler')
        await self.broker.ensure_consumer(another)
        replay = TransactionalWorker(self.broker, self.uow, another, 'stable-handler', lambda u, e: calls.append(2))
        await replay.run_batch()
        self.assertEqual(calls, [1])

    async def test_failed_quarantine_commit_does_not_ack(self):
        from contextlib import contextmanager
        from app.application.messaging.durable import DurableDelivery
        await self.broker.publish(event())
        valid, = await self.broker.fetch('ingest', 1)
        invalid = valid.model_copy(update={'event': None, 'error': 'invalid envelope'})
        @contextmanager
        def broken_uow():
            raise ConnectionError('database unavailable')
            yield
        worker = TransactionalWorker(self.broker, broken_uow, self.spec, 'q', lambda u, e: None, max_attempts=1)
        with self.assertRaises(ConnectionError):
            await worker.process(invalid)
        self.assertNotIn(valid.sequence, self.broker.acked['ingest'])

    async def test_pew_adapter_to_persistence_to_confirmed_events(self):
        with tempfile.TemporaryDirectory() as root:
            blobs = DirectoryBlobStore(root)
            raw = RawItem(platform='file', format='xlsx', source_id='estimate-1', received_at=WHEN,
                          content=blobs.put(workbook(), 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'),
                          mapping=PROFILE.name, binding=BINDING)
            worker = build_durable_ingest(broker=self.broker, uow_factory=self.uow, blobs=blobs, config=CFG,
                                          spec=self.spec, profiles=(PROFILE,))
            await self.broker.publish(raw_item_event(raw))
            self.assertEqual(await worker.run_batch(), 1)
            with self.uow() as u:
                doc, = u.objects.by_kind('project_document')
                self.assertTrue(u.objects.by_kind('wbs_task'))
                pending = u.outbox.pending()
                self.assertTrue(all(e.envelope['kind'] == 'domain.stored' for e in pending))
            sent = await relay_durable_outbox(self.uow, self.broker, WHEN, limit=1000)
            self.assertEqual(sent, len(pending))
            self.assertEqual(len(self.broker.logs['DM_EVENTS']), sent)
            await self.broker.publish(raw_item_event(raw))
            self.assertEqual(await worker.run_batch(), 0)

    async def test_blob_integrity_and_path_traversal(self):
        with tempfile.TemporaryDirectory() as root:
            blobs = DirectoryBlobStore(root)
            ref = blobs.put(b'hello', 'text/plain')
            self.assertEqual(DirectoryBlobStore(root).get(ref), b'hello')
            with self.assertRaises(ValueError):
                blobs.contains('../../secret', ref.sha256)
            (Path(root) / ref.sha256).write_bytes(b'bad')
            self.assertFalse(blobs.contains(ref.key, ref.sha256))
            with self.assertRaises(ValueError):
                blobs.get(ref)


class JetStreamAdapterUnit(unittest.IsolatedAsyncioTestCase):
    async def test_confirmed_publish_has_idempotency_header(self):
        js = types.SimpleNamespace(publish=AsyncMock(return_value=types.SimpleNamespace(stream='DM_RAW', seq=4, duplicate=True)))
        broker = JetStreamBroker(None, js)
        e = event()
        receipt = await broker.publish(e)
        self.assertEqual(receipt.sequence, 4)
        self.assertTrue(receipt.duplicate)
        self.assertEqual(js.publish.call_args.kwargs['headers']['Nats-Msg-Id'], e.event_id)
        self.assertEqual(js.publish.call_args.kwargs['stream'], 'DM_RAW')

    async def test_ack_sync_failure_retains_pending_handle(self):
        broker = JetStreamBroker(None, None)
        from app.application.messaging.durable import DurableDelivery
        d = DurableDelivery(delivery_id='a', stream='DM_RAW', sequence=1, attempt=1, message_key=event().event_id, event=event())
        msg = types.SimpleNamespace(ack_sync=AsyncMock(side_effect=ConnectionError('failed')))
        broker._pending['a'] = ('consumer', msg)
        with self.assertRaises(ConnectionError):
            await broker.ack(d)
        self.assertIn('a', broker._pending)
        msg.ack_sync = AsyncMock()
        await broker.ack(d)
        self.assertNotIn('a', broker._pending)

    async def test_invalid_wire_message_becomes_rejectable_delivery(self):
        from app.application.messaging.durable import DurableDelivery
        meta = types.SimpleNamespace(stream='DM_RAW', sequence=types.SimpleNamespace(stream=1), num_delivered=1)
        message = types.SimpleNamespace(metadata=meta, data=b'not-json', subject=topic_to_subject('raw/file'))
        broker = JetStreamBroker(None, None)
        broker._specs['ingest'] = spec()
        broker._subscriptions['ingest'] = types.SimpleNamespace(fetch=AsyncMock(return_value=[message]))
        module = types.ModuleType('nats.errors'); module.TimeoutError = TimeoutError
        with patch.dict(sys.modules, {'nats.errors': module}):
            d, = await broker.fetch('ingest', 1)
        self.assertIsNone(d.event)
        self.assertEqual(d.error, 'invalid envelope or subject')


@unittest.skipUnless(os.environ.get('DATAMESH_NATS_URL') and importlib.util.find_spec('nats'),
                     'set DATAMESH_NATS_URL and install nats-py; dedicated disposable server required')
class JetStreamIntegration(unittest.IsolatedAsyncioTestCase):
    """Real server test. Never use a production NATS account: this provisions and deletes DM_* streams."""
    async def asyncSetUp(self):
        self.broker = await connect_jetstream((os.environ['DATAMESH_NATS_URL'],))
        await self.broker.provision()

    async def asyncTearDown(self):
        from app.infrastructure.messaging.jetstream import STREAM_FAMILIES
        for name in STREAM_FAMILIES:
            await self.broker.js.delete_stream(name)
        await self.broker.close()

    async def test_publish_dedup_ack_redelivery_replay_and_restart(self):
        await self.broker.provision()  # idempotent, same policies
        a = await self.broker.publish(event('integration'))
        b = await self.broker.publish(event('integration'))
        self.assertEqual(a.sequence, b.sequence)
        self.assertTrue(b.duplicate)
        s = spec()
        await self.broker.ensure_consumer(s)
        d, = await self.broker.fetch(s.durable, 1, 2)
        await self.broker.retry(d, 0.1)
        await asyncio.sleep(0.2)
        d, = await self.broker.fetch(s.durable, 1, 2)
        self.assertGreaterEqual(d.attempt, 2)
        await self.broker.ack(d)
        await self.broker.close()
        self.broker = await connect_jetstream((os.environ['DATAMESH_NATS_URL'],))
        await self.broker.ensure_consumer(s)
        self.assertEqual(await self.broker.fetch(s.durable, 1, 0.2), ())
        replay = spec('rebuild').model_copy(update={'start_sequence': a.sequence})
        await self.broker.ensure_consumer(replay)
        d, = await self.broker.fetch(replay.durable, 1, 2)
        self.assertEqual(d.event, event('integration'))
        await self.broker.ack(d)


if __name__ == '__main__':
    unittest.main()
