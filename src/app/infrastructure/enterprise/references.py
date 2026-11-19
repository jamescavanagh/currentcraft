"""Read an explicit, hash-pinned declarative reference snapshot."""
import hashlib
import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from app.application.enterprise.contracts import ReferenceDictionary, ReferenceSelection
from app.application.enterprise.services import payload_digest, dictionary_digest


@dataclass(frozen=True)
class LoadedReferences:
    dictionary: ReferenceDictionary
    sha256: str
    selection: ReferenceSelection


def _closed_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate reference JSON key: {key}")
        result[key] = value
    return result


def load_references(root: Path, relative_path: str, expected_sha256: str,
                    as_of: datetime) -> LoadedReferences:
    """Caller supplies trusted root/hash/time; data supplies no Python classes."""
    if not root.is_absolute():
        raise ValueError("reference root must be explicit and absolute")
    relative = Path(relative_path)
    if relative.is_absolute() or ".." in relative.parts:
        raise ValueError("reference path must stay within root")
    base = root.resolve(strict=True)
    path = (base / relative).resolve(strict=True)
    if not path.is_relative_to(base) or path.suffix != ".json":
        raise ValueError("reference path must be a JSON file within root")
    if path.stat().st_size > 1024 * 1024:
        raise ValueError("reference file exceeds 1 MiB")
    raw = path.read_bytes()
    digest = hashlib.sha256(raw).hexdigest()
    if digest != expected_sha256:
        raise ValueError("reference file SHA-256 mismatch")
    def invalid_constant(value):
        raise ValueError(f"invalid JSON number: {value}")
    json.loads(raw, object_pairs_hook=_closed_object, parse_constant=invalid_constant)
    dictionary = ReferenceDictionary.model_validate_json(raw)
    if payload_digest(dictionary) != dictionary.payload_sha256:
        raise ValueError("reference payload SHA-256 mismatch")
    if as_of.tzinfo is None or as_of.utcoffset() is None:
        raise ValueError("reference selection time must be timezone-aware")
    if not dictionary.valid_window.start <= as_of < dictionary.valid_window.end:
        raise ValueError("reference file outside validity window")
    selection = ReferenceSelection(dictionary_id=dictionary.dictionary_id,
        dictionary_version=dictionary.version, file_sha256=digest,
        payload_sha256=dictionary.payload_sha256, dictionary_sha256=dictionary_digest(dictionary), as_of=as_of)
    return LoadedReferences(dictionary, digest, selection)
