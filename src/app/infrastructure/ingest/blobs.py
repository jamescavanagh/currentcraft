"""In-memory content-addressed blob store. Only adapters read bytes."""

from __future__ import annotations

import hashlib

from app.application.ingest.contracts import BlobRef


class InMemoryBlobStore:
    def __init__(self, max_bytes: int = 64 * 1024 * 1024):
        self._data: dict[str, bytes] = {}
        self.max_bytes = max_bytes

    def put(self, data: bytes, media_type: str) -> BlobRef:
        if not isinstance(data, (bytes, bytearray)):
            raise TypeError("bytes required")
        if len(data) > self.max_bytes:
            raise ValueError("blob exceeds max_bytes")
        sha = hashlib.sha256(data).hexdigest()
        key = f"blob/{sha[:24]}"
        self._data[key] = bytes(data)
        return BlobRef(key=key, sha256=sha, size=len(data), media_type=media_type)

    def get(self, ref: BlobRef) -> bytes:
        data = self._data.get(ref.key)
        if data is None or hashlib.sha256(data).hexdigest() != ref.sha256:
            raise KeyError(f"blob {ref.key} missing or corrupted")
        return data

    def contains(self, key: str, sha256: str) -> bool:
        d = self._data.get(key)
        return d is not None and hashlib.sha256(d).hexdigest() == sha256
