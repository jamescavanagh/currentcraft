"""Canonical reference adapter: resolves exact references against supplied canonical records.

One instance serves one authorized scope. It reads only allowlisted owner fields and never imports or
executes anything named in data. Extensions are not canonical records and are refused.
"""
import hashlib
from typing import get_args
from uuid import UUID

from app.application.feature_graph.references import CanonicalLookup, OwnerFact, OwnerField
from app.domain.operand.types import CanonicalRef, ExtensionRecord
from app.domain.quality.gate_decision import GateDecision
from app.domain.quality.verification_activity import VerificationActivity
from app.domain.shared.facts import Fact
from app.domain.versioning import VersionedEntity

OWNER_FIELDS = get_args(OwnerField)
# Canonical records without a `kind` field, named explicitly rather than derived from class names.
KIND_OF_CLASS = {GateDecision: "gate_decision", VerificationActivity: "verification_activity"}


def canonical_kind(record: VersionedEntity) -> str:
    kind = KIND_OF_CLASS.get(type(record)) or record.model_dump().get("kind")
    if not isinstance(kind, str):
        raise ValueError("canonical record has no resolvable kind")
    return kind


def _owner(value):
    if isinstance(value, Fact):
        value = value.value
    return value if isinstance(value, UUID) else None


class CanonicalSnapshotPort:
    """Read-only lookups over an explicit set of canonical record versions."""

    def __init__(self, records, *, denied=()):
        self._records, self._identities, self._denied = {}, set(), frozenset(denied)
        for record in records:
            if isinstance(record, ExtensionRecord) or not isinstance(record, VersionedEntity):
                raise TypeError("only canonical records can be resolved")
            key = (record.entity_id, record.record_version)
            if key in self._records:
                raise ValueError("duplicate canonical record version")
            self._records[key] = record
            self._identities.add(record.entity_id)

    def lookup(self, reference: CanonicalRef) -> CanonicalLookup:
        if reference.identity in self._denied:
            return CanonicalLookup(status="access_denied")
        record = self._records.get((reference.identity, reference.version))
        if record is None:
            status = "version_absent" if reference.identity in self._identities else "not_found"
            return CanonicalLookup(status=status)
        owners = tuple(OwnerFact(via=name, identity=_owner(getattr(record, name)))
                       for name in OWNER_FIELDS if name in type(record).model_fields)
        digest = hashlib.sha256(record.model_dump_json().encode()).hexdigest()
        return CanonicalLookup(status="found", kind=canonical_kind(record), identity=record.entity_id,
                               version=record.record_version, record_digest=digest, owners=owners)
