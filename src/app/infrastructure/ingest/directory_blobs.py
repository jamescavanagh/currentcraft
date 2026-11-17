"""Content-addressed filesystem blobs for local/shared-volume ingestion. Not an authorization service.

Single trusted volume, SHA256 names, atomic replacement; no path supplied by a message is ever followed.
Use a separately secured object store for multi-host production deployments.
"""
import hashlib
import os
import tempfile
from pathlib import Path

from app.application.ingest.contracts import BlobRef


class DirectoryBlobStore:
    def __init__(self, root, max_bytes=64 * 1024 * 1024):
        self.max_bytes = max_bytes
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)

    def _path(self, key):
        if not key.startswith('sha256:') or len(key) != 71 or any(c not in '0123456789abcdef' for c in key[7:]):
            raise ValueError('invalid content-addressed blob key')
        path = self.root / key[7:]
        if path.is_symlink():
            raise ValueError('symlink blob refused')
        return path

    def put(self, data: bytes, media_type: str) -> BlobRef:
        if len(data) > self.max_bytes:
            raise ValueError('blob exceeds max_bytes')
        digest = hashlib.sha256(data).hexdigest()
        key = 'sha256:' + digest
        path = self._path(key)
        fd, temp = tempfile.mkstemp(dir=self.root)
        try:
            with os.fdopen(fd, 'wb') as f:
                f.write(data)
                f.flush()
                os.fsync(f.fileno())
            os.replace(temp, path)
        finally:
            if os.path.exists(temp):
                os.unlink(temp)
        return BlobRef(key=key, sha256=digest, size=len(data), media_type=media_type)

    def get(self, ref: BlobRef) -> bytes:
        path = self._path(ref.key)
        if path.stat().st_size > self.max_bytes:
            raise ValueError('blob exceeds max_bytes')
        data = path.read_bytes()
        if len(data) != ref.size or hashlib.sha256(data).hexdigest() != ref.sha256:
            raise ValueError('blob integrity check failed')
        return data

    def contains(self, key: str, sha256: str) -> bool:
        path = self._path(key)
        return (key == 'sha256:' + sha256 and path.is_file() and path.stat().st_size <= self.max_bytes
                and hashlib.sha256(path.read_bytes()).hexdigest() == sha256)
