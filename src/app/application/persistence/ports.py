"""Repository and unit-of-work ports. No drivers, SQL, connections or arrays in any signature.

Every repository is reached through a UnitOfWork: one transaction, committed or rolled back as a whole.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import ContextManager, Literal, Optional, Protocol, runtime_checkable
from uuid import UUID

from app.application.ingest.contracts import DomainObject
from app.application.messaging.contracts import EventEnvelope

from .contracts import (CommandRecord, EdgeRecord, EmbeddingRecord, EmbeddingSpace, OutboxEntry, Reservation,
                        StockPosition, StoreResult, VersionedRecord)


@runtime_checkable
class SourceObjectRepository(Protocol):
    def put(self, obj: DomainObject) -> StoreResult: ...
    def get(self, object_id: str) -> Optional[DomainObject]: ...
    def history(self, object_id: str) -> tuple[DomainObject, ...]: ...
    def by_kind(self, kind: str, limit: int = 1000) -> tuple[DomainObject, ...]: ...
    def related(self, node_id: str, rel_type: Optional[str] = None, direction: Literal["out", "in"] = "out",
                kind: Optional[str] = None) -> tuple[DomainObject, ...]: ...


@runtime_checkable
class GraphRepository(Protocol):
    def edges(self, node_id: str, direction: Literal["out", "in"] = "out", rel_types: tuple[str, ...] = ()) -> tuple[EdgeRecord, ...]: ...
    def traverse(self, start_id: str, rel_types: tuple[str, ...] = (), max_depth: int = 3,
                 direction: Literal["out", "in"] = "out") -> tuple[EdgeRecord, ...]: ...


@runtime_checkable
class AggregateRepository(Protocol):
    def get(self, aggregate_type: str, aggregate_id: UUID) -> Optional[VersionedRecord]: ...
    def history(self, aggregate_type: str, aggregate_id: UUID) -> tuple[VersionedRecord, ...]: ...
    def save(self, record: VersionedRecord, expected_version: Optional[int]) -> VersionedRecord: ...


@runtime_checkable
class CommandLog(Protocol):
    def get(self, command_id: str) -> Optional[CommandRecord]: ...
    def record(self, record: CommandRecord) -> None: ...


@runtime_checkable
class StockRepository(Protocol):
    def put_position(self, position: StockPosition) -> StockPosition: ...
    def get_position(self, stock_id: str) -> Optional[StockPosition]: ...
    def reserve(self, reservation: Reservation) -> Reservation: ...
    def release(self, reservation_id: UUID, command_id: str, at: datetime) -> Reservation: ...
    def reservations(self, stock_id: str, status: Optional[str] = "active") -> tuple[Reservation, ...]: ...


@runtime_checkable
class EmbeddingRepository(Protocol):
    def put(self, record: EmbeddingRecord) -> None: ...
    def get(self, object_id: str, space: EmbeddingSpace) -> Optional[EmbeddingRecord]: ...


@runtime_checkable
class OutboxRepository(Protocol):
    def add(self, event: EventEnvelope, at: datetime) -> bool: ...
    def pending(self, limit: int = 500) -> tuple[OutboxEntry, ...]: ...
    def mark_published(self, event_ids: tuple[str, ...], at: datetime) -> int: ...


class UnitOfWork(Protocol):
    objects: SourceObjectRepository
    graph: GraphRepository
    aggregates: AggregateRepository
    commands: CommandLog
    stock: StockRepository
    embeddings: EmbeddingRepository
    outbox: OutboxRepository

    def __enter__(self) -> "UnitOfWork": ...
    def __exit__(self, exc_type, exc, tb) -> None: ...
    def commit(self) -> None: ...
    def rollback(self) -> None: ...


class UnitOfWorkFactory(Protocol):
    def __call__(self) -> ContextManager[UnitOfWork]: ...


__all__ = ["SourceObjectRepository", "GraphRepository", "AggregateRepository", "CommandLog", "StockRepository",
           "EmbeddingRepository", "OutboxRepository", "UnitOfWork", "UnitOfWorkFactory", "Decimal"]
