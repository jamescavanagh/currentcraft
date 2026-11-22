"""Persistence contracts: what repositories store and return. Pydantic only; no drivers, SQL or connections.

Design source: docs/architecture/PERSISTENCE.md. Repositories persist source occurrences, typed edges, versioned
aggregates, commands, stock and reservations, embeddings and outbox events. The domain never imports any of this.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Annotated, Literal, Optional
from uuid import UUID

from pydantic import Field, JsonValue, NonNegativeInt, PositiveInt, StringConstraints, model_validator

from app.application.common.contracts import _Frozen

SCHEMA_VERSION = "datamesh-persistence/v1"
Ident = Annotated[str, StringConstraints(pattern=r"^[A-Za-z0-9._:-]{1,160}$")]
Level = Annotated[str, StringConstraints(pattern=r"^[A-Za-z0-9._:-]{1,80}$")]
Digest = Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{64}$")]
# 38 digits, 12 after the point: exact quantities and money, never float.
Quantity = Annotated[Decimal, Field(max_digits=38, decimal_places=12)]


def _aware(dt: Optional[datetime], name: str):
    if dt is not None and dt.tzinfo is None:
        raise ValueError(f"{name} must be timezone-aware")


class VersionConflict(Exception):
    """Expected version did not match the stored one. Reload and retry; never overwrite."""


class InsufficientStock(Exception):
    """A reservation would exceed on-hand stock. Nothing was reserved."""


class StoreResult(_Frozen):
    """Outcome of storing one source-occurrence version."""

    object_id: Ident = Field(description="Object id.")
    version_no: PositiveInt = Field(description="Stored version number (1 = first).")
    stored: bool = Field(description="False when this exact digest was already stored (idempotent no-op).")


class EdgeRecord(_Frozen):
    """A typed, evidenced edge read from a stored object's relations, at the object version that asserted it."""

    src_id: Ident = Field(description="Source object id.")
    rel_type: Level = Field(description="Relation type.")
    dst_id: Ident = Field(description="Target id (may not be stored yet).")
    evidence: str = Field(min_length=1, max_length=200, description="Where the relation was read from.")
    src_version: PositiveInt = Field(description="Source object version that asserted the edge.")
    dst_version: Optional[PositiveInt] = Field(default=None, description="Exact target version asserted by the relation; null for legacy unpinned edges.")
    depth: NonNegativeInt = Field(default=1, description="Hops from the start node in a traversal.")


class VersionedRecord(_Frozen):
    """One version of an aggregate: opaque UUID identity, monotonic version, JSON payload (Decimals as strings)."""

    aggregate_type: Level = Field(description="Aggregate type, e.g. work_package.")
    aggregate_id: UUID = Field(description="Opaque identity; never a business number.")
    version: PositiveInt = Field(description="Monotonic version, 1 on create.")
    schema_version: Level = Field(description="Payload schema version.")
    payload: dict[str, JsonValue] = Field(description="model_dump(mode='json') of the aggregate.")
    recorded_at: datetime = Field(description="When this version was recorded (timezone-aware).")
    command_id: Optional[Level] = Field(default=None, description="Command that produced this version.")

    @model_validator(mode="after")
    def _rules(self):
        _aware(self.recorded_at, "recorded_at")
        return self


class CommandRecord(_Frozen):
    """A processed command. Replaying the same command id returns this instead of acting twice."""

    command_id: Level = Field(description="Caller-supplied idempotency key.")
    command_type: Level = Field(description="Command type.")
    outcome: Literal["applied", "rejected"] = Field(description="What happened the first time.")
    result_ref: Optional[str] = Field(default=None, max_length=200, description="Id of what it produced.")
    detail: Optional[str] = Field(default=None, max_length=500, description="Reason when rejected.")
    recorded_at: datetime = Field(description="When it was first processed.")


class StockPosition(_Frozen):
    """Shared stock of one item at one place. Reservations claim it; they never overcommit it."""

    stock_id: Ident = Field(description="Stock position id.")
    item_ref: str = Field(min_length=1, max_length=200, description="Item reference (catalog or ERP item), governed.")
    uom: Level = Field(description="Unit of measure as issued by the owning system.")
    on_hand: Quantity = Field(ge=0, description="Exact on-hand quantity.")
    reserved: Quantity = Field(default=Decimal(0), ge=0, description="Exact reserved quantity.")
    version: PositiveInt = Field(default=1, description="Row version.")

    @model_validator(mode="after")
    def _rules(self):
        if self.reserved > self.on_hand:
            raise ValueError("reserved exceeds on_hand")
        return self

    @property
    def available(self) -> Decimal:
        return self.on_hand - self.reserved


class Reservation(_Frozen):
    """A claim on shared stock by a work package. Not an approval, purchase or custody transfer."""

    reservation_id: UUID = Field(description="Opaque identity.")
    stock_id: Ident = Field(description="Stock position claimed.")
    claimant_ref: Ident = Field(description="Work package or execution id holding the claim.")
    quantity: Quantity = Field(gt=0, description="Exact quantity claimed.")
    status: Literal["active", "released"] = Field(default="active", description="Claim state.")
    command_id: Level = Field(description="Command that created it (idempotency key).")
    created_at: datetime = Field(description="When it was created.")

    @model_validator(mode="after")
    def _rules(self):
        _aware(self.created_at, "created_at")
        return self


class EmbeddingSpace(_Frozen):
    """Model identity of a vector. Vectors from different spaces are never compared."""

    model_name: Level = Field(description="Embedding model name.")
    model_version: Level = Field(description="Model version.")
    dim: PositiveInt = Field(le=65536, description="Dimension.")
    precision: Literal["float32", "float64"] = Field(default="float32", description="Precision the model emits.")


class EmbeddingRecord(_Frozen):
    """Dense and/or sparse vector for one object in one space. Sparse indices are zero-based here."""

    object_id: Ident = Field(description="Object the vector describes.")
    space: EmbeddingSpace = Field(description="Model identity.")
    dense: Optional[tuple[float, ...]] = Field(default=None, description="Dense values, length dim.")
    dense_mask: Optional[tuple[bool, ...]] = Field(default=None, description="True where the value is known; length dim.")
    sparse_indices: tuple[NonNegativeInt, ...] = Field(default=(), description="Zero-based, strictly increasing.")
    sparse_values: tuple[float, ...] = Field(default=(), description="Values for sparse_indices.")
    recorded_at: datetime = Field(description="When recorded.")

    @model_validator(mode="after")
    def _rules(self):
        _aware(self.recorded_at, "recorded_at")
        d = self.space.dim
        if self.dense is None and not self.sparse_indices:
            raise ValueError("needs a dense or a sparse vector")
        if self.dense is not None and len(self.dense) != d:
            raise ValueError("dense length must equal space.dim")
        if self.dense_mask is not None and (self.dense is None or len(self.dense_mask) != d):
            raise ValueError("dense_mask needs a dense vector of the same length")
        if len(self.sparse_indices) != len(self.sparse_values):
            raise ValueError("sparse indices and values differ in length")
        if any(b <= a for a, b in zip(self.sparse_indices, self.sparse_indices[1:])) or any(i >= d for i in self.sparse_indices):
            raise ValueError("sparse indices must be strictly increasing and < dim")
        return self

    @property
    def tolerance(self) -> float:
        """Round-trip tolerance for this precision (relative)."""
        return 1e-6 if self.space.precision == "float32" else 1e-12


class OutboxEntry(_Frozen):
    """An event stored in the same transaction as the change it reports; published after commit."""

    event_id: Digest = Field(description="EventEnvelope.event_id.")
    topic: str = Field(min_length=1, max_length=300, description="Topic.")
    envelope: dict[str, JsonValue] = Field(description="EventEnvelope.model_dump(mode='json').")
    enqueued_at: datetime = Field(description="When stored.")
    published_at: Optional[datetime] = Field(default=None, description="When relayed to the broker.")


CONTRACTS = (StoreResult, EdgeRecord, VersionedRecord, CommandRecord, StockPosition, Reservation, EmbeddingSpace,
             EmbeddingRecord, OutboxEntry)
