"""Private, durable first-receipt selection on one trusted local volume."""

import hashlib
import json
import os
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from uuid import uuid4

from app.application.ingest.contracts import RawItem
from app.application.ingest.http_intake import StoredIntake


class SqliteIntakeReceipts:
    def __init__(self, path: str):
        self.path = Path(path)
        self.path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        if self.path.is_symlink():
            raise ValueError("Invalid receipt storage.")
        fd = os.open(self.path, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
        os.close(fd)
        os.chmod(self.path, 0o600)
        with self._connect() as db:
            db.execute("""CREATE TABLE IF NOT EXISTS intake_receipts (
                submission_key TEXT PRIMARY KEY,
                event_handle TEXT NOT NULL UNIQUE,
                receipt TEXT NOT NULL)""")

    @contextmanager
    def _connect(self):
        db = sqlite3.connect(self.path, timeout=10)
        try:
            with db:
                yield db
        finally:
            db.close()

    def select_first(self, raw: RawItem) -> StoredIntake:
        body = raw.model_dump(mode="json", exclude={"received_at"})
        key = hashlib.sha256(json.dumps(body, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
        candidate = StoredIntake(raw=raw, event_handle="intake_" + uuid4().hex,
                                 source_handle="source_" + uuid4().hex)
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            db.execute("INSERT OR IGNORE INTO intake_receipts VALUES (?, ?, ?)",
                       (key, candidate.event_handle, candidate.model_dump_json()))
            row = db.execute("SELECT receipt FROM intake_receipts WHERE submission_key = ?", (key,)).fetchone()
        return StoredIntake.model_validate_json(row[0])

    def get(self, event_handle: str) -> StoredIntake | None:
        with self._connect() as db:
            row = db.execute("SELECT receipt FROM intake_receipts WHERE event_handle = ?", (event_handle,)).fetchone()
        return StoredIntake.model_validate_json(row[0]) if row else None
