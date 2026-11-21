"""Read a grammar profile file pinned by the SHA-256 of its bytes, then validate it in the application.

Design: docs/domain/LSYS_DOMAIN_VOCABULARY.md. Errors never echo file content.
"""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

from app.application.lsys import GrammarProfile, load_profile

MAX_PROFILE_BYTES = 1 << 20
_HEX64 = re.compile(r"^[0-9a-f]{64}$")


def read_profile(path: Path, expected_sha256: str) -> GrammarProfile:
    """Load ``path`` only if its bytes hash to ``expected_sha256``; the content digest is checked too."""
    if not _HEX64.match(expected_sha256 or ""):
        raise ValueError("expected_sha256 must be 64 lowercase hex characters")
    path = Path(path)
    if path.stat().st_size > MAX_PROFILE_BYTES:
        raise ValueError("grammar profile exceeds the size limit")
    raw = path.read_bytes()
    if hashlib.sha256(raw).hexdigest() != expected_sha256:
        raise ValueError("grammar profile file does not match its pinned SHA-256")
    try:
        data = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("grammar profile is not UTF-8 JSON") from exc
    return load_profile(data)
