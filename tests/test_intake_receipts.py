"""Synthetic receipt persistence and concurrency, not live-service acceptance."""

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from app.application.ingest.contracts import BlobRef, IntakeBinding, RawItem
from app.application.ingest.services import raw_item_event
from app.infrastructure.ingest.intake_receipts import SqliteIntakeReceipts


def raw_item(**changes):
    values = dict(platform="file", format="text", source_id="synthetic-source",
                  received_at=datetime.now(timezone.utc),
                  content=BlobRef(key="sha256:" + "a" * 64, sha256="a" * 64,
                                  size=1, media_type="text/plain"))
    values.update(changes)
    return RawItem(**values)


class ReceiptTests(unittest.TestCase):
    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = str(Path(self.tmp.name) / "receipts.sqlite3")
        self.store = SqliteIntakeReceipts(self.path)

    def test_first_real_timestamp_and_event_survive_restart(self):
        raw = raw_item()
        first = self.store.select_first(raw)
        later = raw.model_copy(update={"received_at": raw.received_at + timedelta(days=1)})
        retry = SqliteIntakeReceipts(self.path).select_first(later)
        self.assertEqual(first, retry)
        self.assertEqual(first.raw.received_at, raw.received_at)
        self.assertEqual(raw_item_event(first.raw), raw_item_event(retry.raw))
        self.assertEqual(self.store.get(first.event_handle), first)
        self.assertIsNone(self.store.get("intake_" + "0" * 32))
        self.assertEqual(Path(self.path).stat().st_mode & 0o777, 0o600)

    def test_concurrent_process_connections_select_one_receipt(self):
        raw = raw_item()
        def select(i):
            return SqliteIntakeReceipts(self.path).select_first(
                raw.model_copy(update={"received_at": raw.received_at + timedelta(seconds=i)}))
        with ThreadPoolExecutor(max_workers=8) as pool:
            results = list(pool.map(select, range(24)))
        self.assertTrue(all(r == results[0] for r in results))

    def test_complete_binding_mapping_format_content_and_source_are_keyed(self):
        base = raw_item()
        first = self.store.select_first(base)
        binding = IntakeBinding(subject_kind="project", subject_namespace="synthetic",
                                subject_ref="demo", document_type="estimate", revision_label="one")
        variants = [
            base.model_copy(update={"source_id": "synthetic-other"}),
            base.model_copy(update={"mapping": "synthetic-profile"}),
            base.model_copy(update={"format": "xlsx", "mapping": "synthetic-profile"}),
            base.model_copy(update={"content": base.content.model_copy(update={"sha256": "b" * 64, "key": "sha256:" + "b" * 64})}),
            base.model_copy(update={"binding": binding}),
            base.model_copy(update={"binding": binding.model_copy(update={"revision_label": "two"})}),
        ]
        handles = {first.event_handle, *(self.store.select_first(v).event_handle for v in variants)}
        self.assertEqual(len(handles), 7)

    def test_existing_event_constructor_remains_exact(self):
        raw = raw_item()
        first = self.store.select_first(raw)
        self.assertEqual(raw_item_event(first.raw).model_dump_json(), raw_item_event(raw).model_dump_json())
        self.assertNotIn(raw.source_id, first.event_handle)
        self.assertNotIn(raw.source_id, first.source_handle)
