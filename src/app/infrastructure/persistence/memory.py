"""In-memory repositories with the same contract as the SQL ones. For tests and offline runs; single process.

A unit of work works on a deep copy of the store and swaps it in on commit, so rollback discards everything.
"""

from __future__ import annotations

import copy
import threading
from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal, Optional
from uuid import UUID

from app.application.ingest.contracts import DomainObject
from app.application.messaging.contracts import EventEnvelope
from app.application.persistence.contracts import (CommandRecord, EdgeRecord, EmbeddingRecord, EmbeddingSpace, InsufficientStock,
                                                   OutboxEntry, Reservation, StockPosition, StoreResult, VersionConflict,
                                                   VersionedRecord)

from .repositories import MAX_DEPTH


@dataclass
class MemoryState:
    objects: dict = field(default_factory=dict)        # object_id -> [DomainObject, ...] (index = version - 1)
    aggregates: dict = field(default_factory=dict)     # (type, id) -> [VersionedRecord, ...]
    commands: dict = field(default_factory=dict)
    stock: dict = field(default_factory=dict)
    reservations: dict = field(default_factory=dict)   # reservation_id -> Reservation
    embeddings: dict = field(default_factory=dict)     # (object_id, model, version) -> EmbeddingRecord
    outbox: dict = field(default_factory=dict)         # event_id -> OutboxEntry


class _Repo:
    def __init__(self, uow: "MemoryUnitOfWork"):
        self._uow = uow

    @property
    def s(self) -> MemoryState:
        return self._uow.state


class MemorySourceObjectRepository(_Repo):
    def put(self, obj: DomainObject) -> StoreResult:
        vs = self.s.objects.setdefault(obj.object_id, [])
        if vs and vs[-1].digest() == obj.digest():
            return StoreResult(object_id=obj.object_id, version_no=len(vs), stored=False)
        vs.append(obj)
        return StoreResult(object_id=obj.object_id, version_no=len(vs), stored=True)

    def get(self, object_id: str) -> Optional[DomainObject]:
        vs = self.s.objects.get(object_id)
        return vs[-1] if vs else None

    def history(self, object_id: str) -> tuple[DomainObject, ...]:
        return tuple(self.s.objects.get(object_id, ()))

    def by_kind(self, kind: str, limit: int = 1000) -> tuple[DomainObject, ...]:
        return tuple(o for _, o in sorted((k, v[-1]) for k, v in self.s.objects.items() if v[-1].kind == kind))[:limit]

    def _current_edges(self):
        for oid, vs in self.s.objects.items():
            for i, r in enumerate(vs[-1].relations):
                yield EdgeRecord(src_id=oid, rel_type=r.type, dst_id=r.target_id, evidence=r.evidence, src_version=len(vs)), i

    def related(self, node_id: str, rel_type: Optional[str] = None, direction: Literal["out", "in"] = "out",
                kind: Optional[str] = None) -> tuple[DomainObject, ...]:
        ids = {(e.dst_id if direction == "out" else e.src_id) for e, _ in self._current_edges()
               if (e.src_id if direction == "out" else e.dst_id) == node_id and (rel_type is None or e.rel_type == rel_type)}
        out = [self.get(i) for i in sorted(ids)]
        return tuple(o for o in out if o is not None and (kind is None or o.kind == kind))


class MemoryGraphRepository(_Repo):
    def _edges(self):
        return MemorySourceObjectRepository(self._uow)._current_edges()

    def edges(self, node_id: str, direction: Literal["out", "in"] = "out", rel_types: tuple[str, ...] = ()) -> tuple[EdgeRecord, ...]:
        near = "src_id" if direction == "out" else "dst_id"
        hits = [(e.src_id, i, e) for e, i in self._edges() if getattr(e, near) == node_id and (not rel_types or e.rel_type in rel_types)]
        return tuple(e for _, _, e in sorted(hits, key=lambda t: (t[0], t[1])))

    def traverse(self, start_id: str, rel_types: tuple[str, ...] = (), max_depth: int = 3,
                 direction: Literal["out", "in"] = "out") -> tuple[EdgeRecord, ...]:
        if not 1 <= max_depth <= MAX_DEPTH:
            raise ValueError(f"max_depth must be 1..{MAX_DEPTH}")
        near, far = ("src_id", "dst_id") if direction == "out" else ("dst_id", "src_id")
        all_edges = [e for e, _ in self._edges() if not rel_types or e.rel_type in rel_types]
        best: dict = {}
        frontier = {start_id}
        for depth in range(1, max_depth + 1):
            nxt = set()
            for e in all_edges:
                if getattr(e, near) in frontier:
                    key = (e.src_id, e.rel_type, e.dst_id, e.evidence, e.src_version)
                    best.setdefault(key, depth)
                    nxt.add(getattr(e, far))
            frontier = nxt
            if not frontier:
                break
        return tuple(EdgeRecord(src_id=k[0], rel_type=k[1], dst_id=k[2], evidence=k[3], src_version=k[4], depth=d)
                     for k, d in sorted(best.items(), key=lambda kv: (kv[1], kv[0][0], kv[0][1], kv[0][2])))


class MemoryAggregateRepository(_Repo):
    def get(self, aggregate_type: str, aggregate_id: UUID) -> Optional[VersionedRecord]:
        vs = self.s.aggregates.get((aggregate_type, aggregate_id))
        return vs[-1] if vs else None

    def history(self, aggregate_type: str, aggregate_id: UUID) -> tuple[VersionedRecord, ...]:
        return tuple(self.s.aggregates.get((aggregate_type, aggregate_id), ()))

    def save(self, record: VersionedRecord, expected_version: Optional[int]) -> VersionedRecord:
        key = (record.aggregate_type, record.aggregate_id)
        current = len(self.s.aggregates.get(key, ()))
        if (expected_version or 0) != current or (expected_version is None and current):
            raise VersionConflict(f"{key[0]}/{key[1]}: expected version {expected_version}, stored {current or None}")
        rec = record.model_copy(update={"version": current + 1})
        self.s.aggregates.setdefault(key, []).append(rec)
        return rec


class MemoryCommandLog(_Repo):
    def get(self, command_id: str) -> Optional[CommandRecord]:
        return self.s.commands.get(command_id)

    def record(self, record: CommandRecord) -> None:
        if record.command_id in self.s.commands:
            raise VersionConflict(f"command {record.command_id} already recorded")
        self.s.commands[record.command_id] = record


class MemoryStockRepository(_Repo):
    def put_position(self, position: StockPosition) -> StockPosition:
        cur = self.s.stock.get(position.stock_id)
        if cur is None:
            new = position.model_copy(update={"reserved": 0, "version": 1})
        else:
            if cur.reserved > position.on_hand:
                raise InsufficientStock(f"{position.stock_id}: on_hand below reserved")
            new = cur.model_copy(update={"item_ref": position.item_ref, "uom": position.uom, "on_hand": position.on_hand,
                                         "version": cur.version + 1})
        self.s.stock[position.stock_id] = StockPosition.model_validate(new.model_dump())
        return self.s.stock[position.stock_id]

    def get_position(self, stock_id: str) -> Optional[StockPosition]:
        return self.s.stock.get(stock_id)

    def reserve(self, reservation: Reservation) -> Reservation:
        for r in self.s.reservations.values():
            if r.command_id == reservation.command_id:
                return r
        pos = self.s.stock.get(reservation.stock_id)
        if pos is None:
            raise KeyError(f"no stock position {reservation.stock_id}")
        if pos.reserved + reservation.quantity > pos.on_hand:
            raise InsufficientStock(f"{reservation.stock_id}: {reservation.quantity} requested, {pos.available} available")
        self.s.stock[pos.stock_id] = pos.model_copy(update={"reserved": pos.reserved + reservation.quantity, "version": pos.version + 1})
        r = reservation.model_copy(update={"status": "active"})
        self.s.reservations[r.reservation_id] = r
        return r

    def release(self, reservation_id: UUID, command_id: str, at: datetime) -> Reservation:
        r = self.s.reservations.get(reservation_id)
        if r is None:
            raise KeyError(f"no reservation {reservation_id}")
        if r.status == "active":
            pos = self.s.stock[r.stock_id]
            self.s.stock[r.stock_id] = pos.model_copy(update={"reserved": pos.reserved - r.quantity, "version": pos.version + 1})
            r = self.s.reservations[reservation_id] = r.model_copy(update={"status": "released"})
        return r

    def reservations(self, stock_id: str, status: Optional[str] = "active") -> tuple[Reservation, ...]:
        rs = [r for r in self.s.reservations.values() if r.stock_id == stock_id and (status is None or r.status == status)]
        return tuple(sorted(rs, key=lambda r: (r.created_at, str(r.reservation_id))))


class MemoryEmbeddingRepository(_Repo):
    def put(self, record: EmbeddingRecord) -> None:
        self.s.embeddings[(record.object_id, record.space.model_name, record.space.model_version)] = record

    def get(self, object_id: str, space: EmbeddingSpace) -> Optional[EmbeddingRecord]:
        r = self.s.embeddings.get((object_id, space.model_name, space.model_version))
        if r is not None and (r.space.dim != space.dim or r.space.precision != space.precision):
            raise ValueError(f"{object_id}: stored space {r.space.precision}/{r.space.dim} differs from requested "
                             f"{space.precision}/{space.dim}")
        return r


class MemoryOutboxRepository(_Repo):
    def add(self, event: EventEnvelope, at: datetime) -> bool:
        if event.event_id in self.s.outbox:
            return False
        self.s.outbox[event.event_id] = OutboxEntry(event_id=event.event_id, topic=event.topic,
                                                    envelope=event.model_dump(mode="json"), enqueued_at=at)
        return True

    def pending(self, limit: int = 500) -> tuple[OutboxEntry, ...]:
        p = [e for e in self.s.outbox.values() if e.published_at is None]
        return tuple(sorted(p, key=lambda e: (e.enqueued_at, e.event_id))[:limit])

    def mark_published(self, event_ids: tuple[str, ...], at: datetime) -> int:
        n = 0
        for i in event_ids:
            e = self.s.outbox.get(i)
            if e is not None and e.published_at is None:
                self.s.outbox[i] = e.model_copy(update={"published_at": at})
                n += 1
        return n


class MemoryStore:
    """Shared committed state. One writer at a time (a process-local lock stands in for row locks)."""

    def __init__(self):
        self.state = MemoryState()
        self.lock = threading.RLock()

    def __call__(self) -> "MemoryUnitOfWork":
        return MemoryUnitOfWork(self)


class MemoryUnitOfWork:
    def __init__(self, store: MemoryStore):
        self._store = store
        self.state: MemoryState = None  # type: ignore[assignment]
        self.objects = MemorySourceObjectRepository(self)
        self.graph = MemoryGraphRepository(self)
        self.aggregates = MemoryAggregateRepository(self)
        self.commands = MemoryCommandLog(self)
        self.stock = MemoryStockRepository(self)
        self.embeddings = MemoryEmbeddingRepository(self)
        self.outbox = MemoryOutboxRepository(self)
        self._done = False

    def __enter__(self):
        self._store.lock.acquire()
        self.state = copy.deepcopy(self._store.state)
        return self

    def __exit__(self, exc_type, exc, tb):
        self.state = None  # uncommitted work is discarded
        self._store.lock.release()

    def commit(self):
        self._store.state = self.state
        self.state = copy.deepcopy(self.state)
        self._done = True

    def rollback(self):
        self.state = copy.deepcopy(self._store.state)
        self._done = True


__all__ = ["MemoryStore", "MemoryUnitOfWork", "MemoryState"]
