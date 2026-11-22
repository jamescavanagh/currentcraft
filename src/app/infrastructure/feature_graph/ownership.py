"""Ownership profile loader: hash-pinned JSON from an explicitly configured private REF root.

Follows the enterprise reference pattern: explicit absolute root, contained path, no symlinks, size
limit, SHA-256 match, closed JSON and an as-of check inside the validity window. It also checks that
the profile is drawn from the stated referenced standard: every rule cites a concept of that exact
framework profile, and the concept maps to the subject or owner of the rule.
"""
import hashlib
import json
from datetime import datetime
from pathlib import Path

from app.application.feature_graph.references import OwnershipProfile

MAX_BYTES = 1024 * 1024
# Framework profiles name domain classes; only these map to canonical kinds for ownership.
CLASS_KINDS = {"Project": "project", "Document": "document", "Revision": "revision", "Order": "order",
               "Subsystem": "subsystem", "System": "system", "Phase": "phase", "WBS": "wbs",
               "ProductDefinition": "product_definition", "AssetInstance": "asset_instance",
               "Contract": "contract", "Shipment": "shipment", "BOM": "bom"}


def _closed(pairs):
    out = {}
    for key, value in pairs:
        if key in out:
            raise ValueError("duplicate JSON key")
        out[key] = value
    return out


def _read(root: Path, relative: str, expected_sha256: str) -> bytes:
    if not isinstance(root, Path) or not root.is_absolute():
        raise ValueError("REF root must be an explicit absolute path")
    base = root.resolve(strict=True)
    rel = Path(relative)
    if not relative or rel.is_absolute() or ".." in rel.parts or "\\" in relative:
        raise ValueError("profile path must stay inside the REF root")
    current = base
    for part in rel.parts:
        current = current / part
        if current.is_symlink():
            raise ValueError("symlinks are not accepted in REF paths")
    path = (base / rel).resolve(strict=True)
    if not path.is_relative_to(base) or not path.is_file() or path.stat().st_size > MAX_BYTES:
        raise ValueError("profile must be a bounded regular file inside the REF root")
    raw = path.read_bytes()
    if hashlib.sha256(raw).hexdigest() != expected_sha256:
        raise ValueError("ownership profile SHA-256 mismatch")
    return raw


def load_ownership_profile(root: Path, relative: str, expected_sha256: str, as_of: datetime) -> OwnershipProfile:
    """Load and validate one pinned ownership profile; it must be valid at `as_of`."""
    raw = _read(root, relative, expected_sha256)

    def invalid(value):
        raise ValueError("invalid JSON constant")

    profile = OwnershipProfile.model_validate(json.loads(raw, object_pairs_hook=_closed, parse_constant=invalid))
    if not profile.valid_at(as_of):
        raise ValueError("ownership profile is not valid at as_of")
    return profile


def check_standard_binding(profile: OwnershipProfile, framework_profile: dict) -> None:
    """Fail unless every rule is drawn from the exact referenced framework profile."""
    pin = profile.standard
    if (framework_profile.get("framework_id"), framework_profile.get("framework_edition"),
            framework_profile.get("profile_version"), framework_profile.get("source_digest")) != (
            pin.framework_id, pin.framework_edition, pin.profile_version, pin.source_digest):
        raise ValueError("ownership profile is not pinned to this framework profile")
    concepts = {c["concept_id"]: c for c in framework_profile.get("concepts", ())}
    for rule in profile.rules:
        concept = concepts.get(rule.concept_id)
        if concept is None:
            raise ValueError("ownership rule cites a concept outside the referenced standard")
        kind = CLASS_KINDS.get(concept.get("maps_to") or "")
        if kind not in (rule.subject_kind, rule.owner_kind):
            raise ValueError("ownership rule concept does not map to its subject or owner")
