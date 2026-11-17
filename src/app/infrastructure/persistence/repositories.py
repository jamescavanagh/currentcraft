"""SQL repositories (PostgreSQL 18 target). Every value is a bound parameter; every write runs inside the caller's
unit-of-work transaction. Constraint and serialization failures surface as VersionConflict so the caller can retry.
"""

from __future__ import annotations

import json
from contextlib import contextmanager
from datetime import datetime, timezone
from decimal import Decimal
from typing import Literal, Optional
from uuid import UUID

from app.application.ingest.contracts import DomainObject
from app.application.messaging.contracts import EventEnvelope
from app.application.persistence.contracts import (CommandRecord, EdgeRecord, EmbeddingRecord, EmbeddingSpace, InsufficientStock,
                                                   OutboxEntry, Reservation, StockPosition, StoreResult, VersionConflict,
                                                   VersionedRecord)

from .dialect import Json
from .sql import SqlExecutor, placeholders
from .vectors import dense_literal, sparse_literal

MAX_DEPTH = 6


def _json(v):
    return json.loads(v) if isinstance(v, str) else v


def _now():
    return datetime.now(timezone.utc)


class _Repo:
    def __init__(self, ex: SqlExecutor):
        self.ex = ex

    @contextmanager
    def _conflicts(self, what: str):
        try:
            yield
        except (VersionConflict, InsufficientStock):
            raise
        except Exception as e:
            if self.ex.dialect.is_conflict(e):
                raise VersionConflict(f"{what}: {type(e).__name__}") from e
            raise


class SqlSourceObjectRepository(_Repo):
    _CURRENT = ("FROM dm_edges e JOIN dm_source_object_heads hs ON hs.object_id = e.src_id AND hs.version_no = e.src_version ")

    def put(self, obj: DomainObject) -> StoreResult:
        digest = obj.digest()
        head = self.ex.rows("SELECT version_no, digest FROM dm_source_object_heads WHERE object_id = %s", (obj.object_id,))
        if head and head[0]["digest"].strip() == digest:
            return StoreResult(object_id=obj.object_id, version_no=head[0]["version_no"], stored=False)
        prev = head[0]["version_no"] if head else 0
        v = prev + 1
        p = obj.provenance
        with self._conflicts(f"object {obj.object_id}"):
            self.ex.run("INSERT INTO dm_source_objects (object_id, version_no, kind, digest, content_sha256, adapter, adapter_version, "
                        "body, received_at, stored_at) VALUES (%s, %s, %s, %s, %s, %s, %s, %s{JSONCAST}, %s, %s)",
                        (obj.object_id, v, obj.kind, digest, p.content_sha256, p.adapter, p.adapter_version,
                         Json(obj.model_dump_json()), p.received_at, _now()))
            if prev == 0:
                self.ex.run("INSERT INTO dm_source_object_heads (object_id, version_no, kind, digest) VALUES (%s, %s, %s, %s)",
                            (obj.object_id, v, obj.kind, digest))
            else:
                moved = self.ex.rows("UPDATE dm_source_object_heads SET version_no = %s, digest = %s, kind = %s "
                                     "WHERE object_id = %s AND version_no = %s RETURNING version_no",
                                     (v, digest, obj.kind, obj.object_id, prev))
                if not moved:
                    raise VersionConflict(f"object {obj.object_id} moved past version {prev}")
            for i, r in enumerate(obj.relations):
                self.ex.run("INSERT INTO dm_edges (src_id, src_version, ordinal, rel_type, dst_id, evidence) VALUES (%s, %s, %s, %s, %s, %s)",
                            (obj.object_id, v, i, r.type, r.target_id, r.evidence))
        return StoreResult(object_id=obj.object_id, version_no=v, stored=True)

    @staticmethod
    def _obj(row) -> DomainObject:
        b = row["body"]
        return DomainObject.model_validate_json(b) if isinstance(b, str) else DomainObject.model_validate(b)

    def get(self, object_id: str) -> Optional[DomainObject]:
        rows = self.ex.rows("SELECT o.body FROM dm_source_object_heads h JOIN dm_source_objects o "
                            "ON o.object_id = h.object_id AND o.version_no = h.version_no WHERE h.object_id = %s", (object_id,))
        return self._obj(rows[0]) if rows else None

    def history(self, object_id: str) -> tuple[DomainObject, ...]:
        return tuple(self._obj(r) for r in self.ex.rows(
            "SELECT body FROM dm_source_objects WHERE object_id = %s ORDER BY version_no", (object_id,)))

    def by_kind(self, kind: str, limit: int = 1000) -> tuple[DomainObject, ...]:
        return tuple(self._obj(r) for r in self.ex.rows(
            "SELECT o.body FROM dm_source_object_heads h JOIN dm_source_objects o ON o.object_id = h.object_id "
            "AND o.version_no = h.version_no WHERE h.kind = %s ORDER BY h.object_id LIMIT %s", (kind, int(limit))))

    def related(self, node_id: str, rel_type: Optional[str] = None, direction: Literal["out", "in"] = "out",
                kind: Optional[str] = None) -> tuple[DomainObject, ...]:
        near, far = ("src_id", "dst_id") if direction == "out" else ("dst_id", "src_id")
        sql = (f"SELECT o.body FROM dm_source_object_heads h JOIN dm_source_objects o ON o.object_id = h.object_id "
               f"AND o.version_no = h.version_no WHERE h.object_id IN (SELECT e.{far} {self._CURRENT}WHERE e.{near} = %s")
        params: list = [node_id]
        if rel_type:
            sql += " AND e.rel_type = %s"
            params.append(rel_type)
        sql += ")"
        if kind:
            sql += " AND h.kind = %s"
            params.append(kind)
        return tuple(self._obj(r) for r in self.ex.rows(sql + " ORDER BY h.object_id", params))


class SqlGraphRepository(_Repo):
    _CURRENT = SqlSourceObjectRepository._CURRENT

    def edges(self, node_id: str, direction: Literal["out", "in"] = "out", rel_types: tuple[str, ...] = ()) -> tuple[EdgeRecord, ...]:
        near = "src_id" if direction == "out" else "dst_id"
        sql = f"SELECT e.src_id, e.rel_type, e.dst_id, e.evidence, e.src_version {self._CURRENT}WHERE e.{near} = %s"
        params: list = [node_id]
        if rel_types:
            sql += f" AND e.rel_type IN ({placeholders(len(rel_types))})"
            params += list(rel_types)
        return tuple(EdgeRecord(**r) for r in self.ex.rows(sql + " ORDER BY e.src_id, e.ordinal", params))

    def traverse(self, start_id: str, rel_types: tuple[str, ...] = (), max_depth: int = 3,
                 direction: Literal["out", "in"] = "out") -> tuple[EdgeRecord, ...]:
        if not 1 <= max_depth <= MAX_DEPTH:
            raise ValueError(f"max_depth must be 1..{MAX_DEPTH}")
        near, far = ("src_id", "dst_id") if direction == "out" else ("dst_id", "src_id")
        rel = f" AND e.rel_type IN ({placeholders(len(rel_types))})" if rel_types else ""
        sql = ("WITH RECURSIVE walk (src_id, rel_type, dst_id, evidence, src_version, depth, frontier) AS ("
               f" SELECT e.src_id, e.rel_type, e.dst_id, e.evidence, e.src_version, 1, e.{far} {self._CURRENT}WHERE e.{near} = %s{rel}"
               " UNION ALL"
               f" SELECT e.src_id, e.rel_type, e.dst_id, e.evidence, e.src_version, w.depth + 1, e.{far} FROM walk w"
               f" JOIN dm_edges e ON e.{near} = w.frontier"
               " JOIN dm_source_object_heads hs ON hs.object_id = e.src_id AND hs.version_no = e.src_version"
               f" WHERE w.depth < %s{rel})"
               " SELECT src_id, rel_type, dst_id, evidence, src_version, MIN(depth) AS depth FROM walk"
               " GROUP BY src_id, rel_type, dst_id, evidence, src_version ORDER BY depth, src_id, rel_type, dst_id")
        params = [start_id, *rel_types, int(max_depth), *rel_types]
        return tuple(EdgeRecord(**r) for r in self.ex.rows(sql, params))


class SqlAggregateRepository(_Repo):
    _COLS = "aggregate_type, aggregate_id, version, schema_version, payload, recorded_at, command_id"

    def _rec(self, r) -> VersionedRecord:
        return VersionedRecord(**{**r, "payload": _json(r["payload"])})

    def get(self, aggregate_type: str, aggregate_id: UUID) -> Optional[VersionedRecord]:
        rows = self.ex.rows(f"SELECT {self._COLS} FROM dm_aggregates WHERE aggregate_type = %s AND aggregate_id = %s",
                            (aggregate_type, aggregate_id))
        return self._rec(rows[0]) if rows else None

    def history(self, aggregate_type: str, aggregate_id: UUID) -> tuple[VersionedRecord, ...]:
        return tuple(self._rec(r) for r in self.ex.rows(
            f"SELECT {self._COLS} FROM dm_aggregate_versions WHERE aggregate_type = %s AND aggregate_id = %s ORDER BY version",
            (aggregate_type, aggregate_id)))

    def save(self, record: VersionedRecord, expected_version: Optional[int]) -> VersionedRecord:
        """Compare-and-swap: expected None creates version 1; otherwise the stored version must equal expected."""
        new_v = (expected_version or 0) + 1
        rec = record.model_copy(update={"version": new_v})
        vals = (rec.schema_version, Json(rec.payload), rec.recorded_at, rec.command_id)
        with self._conflicts(f"{rec.aggregate_type}/{rec.aggregate_id}"):
            if expected_version is None:
                got = self.ex.rows("INSERT INTO dm_aggregates (aggregate_type, aggregate_id, version, schema_version, payload, recorded_at, "
                                   "command_id) VALUES (%s, %s, %s, %s, %s{JSONCAST}, %s, %s) ON CONFLICT DO NOTHING RETURNING version",
                                   (rec.aggregate_type, rec.aggregate_id, new_v, *vals))
            else:
                got = self.ex.rows("UPDATE dm_aggregates SET version = %s, schema_version = %s, payload = %s{JSONCAST}, recorded_at = %s, "
                                   "command_id = %s WHERE aggregate_type = %s AND aggregate_id = %s AND version = %s RETURNING version",
                                   (new_v, *vals, rec.aggregate_type, rec.aggregate_id, expected_version))
            if not got:
                raise VersionConflict(f"{rec.aggregate_type}/{rec.aggregate_id}: expected version {expected_version}")
            self.ex.run("INSERT INTO dm_aggregate_versions (aggregate_type, aggregate_id, version, schema_version, payload, recorded_at, "
                        "command_id) VALUES (%s, %s, %s, %s, %s{JSONCAST}, %s, %s)", (rec.aggregate_type, rec.aggregate_id, new_v, *vals))
        return rec


class SqlCommandLog(_Repo):
    def get(self, command_id: str) -> Optional[CommandRecord]:
        rows = self.ex.rows("SELECT command_id, command_type, outcome, result_ref, detail, recorded_at FROM dm_commands "
                            "WHERE command_id = %s", (command_id,))
        return CommandRecord(**rows[0]) if rows else None

    def record(self, record: CommandRecord) -> None:
        with self._conflicts(f"command {record.command_id}"):
            got = self.ex.rows("INSERT INTO dm_commands (command_id, command_type, outcome, result_ref, detail, recorded_at) "
                               "VALUES (%s, %s, %s, %s, %s, %s) ON CONFLICT DO NOTHING RETURNING command_id",
                               (record.command_id, record.command_type, record.outcome, record.result_ref, record.detail, record.recorded_at))
        if not got:
            raise VersionConflict(f"command {record.command_id} already recorded")


class SqlStockRepository(_Repo):
    _RES = "reservation_id, stock_id, claimant_ref, quantity, status, command_id, created_at"

    def put_position(self, position: StockPosition) -> StockPosition:
        """Create, or set on-hand for, a position. Lowering on-hand below what is reserved raises InsufficientStock."""
        with self._conflicts(f"stock {position.stock_id}"):
            got = self.ex.rows("UPDATE dm_stock_positions SET item_ref = %s, uom = %s, on_hand = %s, version = version + 1 "
                               "WHERE stock_id = %s AND reserved <= %s RETURNING version",
                               (position.item_ref, position.uom, position.on_hand, position.stock_id, position.on_hand))
            if not got:
                if self.get_position(position.stock_id) is not None:
                    raise InsufficientStock(f"{position.stock_id}: on_hand below reserved")
                self.ex.run("INSERT INTO dm_stock_positions (stock_id, item_ref, uom, on_hand, reserved, version) VALUES (%s, %s, %s, %s, 0, 1)",
                            (position.stock_id, position.item_ref, position.uom, position.on_hand))
        return self.get_position(position.stock_id)

    def get_position(self, stock_id: str) -> Optional[StockPosition]:
        rows = self.ex.rows("SELECT stock_id, item_ref, uom, on_hand, reserved, version FROM dm_stock_positions WHERE stock_id = %s", (stock_id,))
        return StockPosition(**rows[0]) if rows else None

    def _by_command(self, command_id) -> Optional[Reservation]:
        rows = self.ex.rows(f"SELECT {self._RES} FROM dm_reservations WHERE command_id = %s", (command_id,))
        return Reservation(**rows[0]) if rows else None

    def reserve(self, reservation: Reservation) -> Reservation:
        """Idempotent per command id. The conditional update is atomic per row, so competing reservations cannot
        overcommit: under READ COMMITTED a second writer re-checks reserved + qty <= on_hand after the first commits."""
        prior = self._by_command(reservation.command_id)
        if prior is not None:
            return prior
        q = reservation.quantity
        with self._conflicts(f"reservation {reservation.command_id}"):
            got = self.ex.rows("UPDATE dm_stock_positions SET reserved = reserved + %s, version = version + 1 "
                               "WHERE stock_id = %s AND reserved + %s <= on_hand RETURNING reserved", (q, reservation.stock_id, q))
            if not got:
                pos = self.get_position(reservation.stock_id)
                if pos is None:
                    raise KeyError(f"no stock position {reservation.stock_id}")
                raise InsufficientStock(f"{reservation.stock_id}: {q} requested, {pos.available} available")
            self.ex.run(f"INSERT INTO dm_reservations ({self._RES}) VALUES (%s, %s, %s, %s, %s, %s, %s)",
                        (reservation.reservation_id, reservation.stock_id, reservation.claimant_ref, q, "active",
                         reservation.command_id, reservation.created_at))
        return reservation

    def release(self, reservation_id: UUID, command_id: str, at: datetime) -> Reservation:
        with self._conflicts(f"release {reservation_id}"):
            got = self.ex.rows("UPDATE dm_reservations SET status = 'released', released_at = %s, release_command_id = %s "
                               "WHERE reservation_id = %s AND status = 'active' RETURNING stock_id, quantity", (at, command_id, reservation_id))
            if got:
                self.ex.run("UPDATE dm_stock_positions SET reserved = reserved - %s, version = version + 1 WHERE stock_id = %s",
                            (got[0]["quantity"], got[0]["stock_id"]))
        rows = self.ex.rows(f"SELECT {self._RES} FROM dm_reservations WHERE reservation_id = %s", (reservation_id,))
        if not rows:
            raise KeyError(f"no reservation {reservation_id}")
        return Reservation(**rows[0])

    def reservations(self, stock_id: str, status: Optional[str] = "active") -> tuple[Reservation, ...]:
        sql, params = f"SELECT {self._RES} FROM dm_reservations WHERE stock_id = %s", [stock_id]
        if status:
            sql += " AND status = %s"
            params.append(status)
        return tuple(Reservation(**r) for r in self.ex.rows(sql + " ORDER BY created_at, reservation_id", params))


class SqlEmbeddingRepository(_Repo):
    def put(self, record: EmbeddingRecord) -> None:
        s = record.space
        vals = (s.dim, s.precision, list(record.dense) if record.dense is not None else None,
                list(record.dense_mask) if record.dense_mask is not None else None,
                list(record.sparse_indices) or None, list(record.sparse_values) or None, record.recorded_at)
        key = (record.object_id, s.model_name, s.model_version)
        with self._conflicts(f"embedding {record.object_id}"):
            got = self.ex.rows("UPDATE dm_embeddings SET dim = %s, float_precision = %s, dense = %s, dense_mask = %s, sparse_indices = %s, "
                               "sparse_values = %s, recorded_at = %s WHERE object_id = %s AND model_name = %s AND model_version = %s "
                               "RETURNING object_id", (*vals, *key))
            if not got:
                self.ex.run("INSERT INTO dm_embeddings (dim, float_precision, dense, dense_mask, sparse_indices, sparse_values, recorded_at, "
                            "object_id, model_name, model_version) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)", (*vals, *key))
            if self.ex.dialect.pgvector:
                self.ex.run("UPDATE dm_embeddings SET dense_vec = %s::vector, sparse_vec = %s::sparsevec "
                            "WHERE object_id = %s AND model_name = %s AND model_version = %s",
                            (dense_literal(record.dense) if record.dense is not None else None,
                             sparse_literal(record.sparse_indices, record.sparse_values, s.dim) if record.sparse_indices else None, *key))

    def get(self, object_id: str, space: EmbeddingSpace) -> Optional[EmbeddingRecord]:
        rows = self.ex.rows("SELECT dim, float_precision, dense, dense_mask, sparse_indices, sparse_values, recorded_at FROM dm_embeddings "
                            "WHERE object_id = %s AND model_name = %s AND model_version = %s",
                            (object_id, space.model_name, space.model_version))
        if not rows:
            return None
        r = rows[0]
        if r["dim"] != space.dim or r["float_precision"] != space.precision:
            raise ValueError(f"{object_id}: stored space {r['float_precision']}/{r['dim']} differs from requested {space.precision}/{space.dim}")
        return EmbeddingRecord(object_id=object_id, space=space,
                               dense=tuple(r["dense"]) if r["dense"] is not None else None,
                               dense_mask=tuple(r["dense_mask"]) if r["dense_mask"] is not None else None,
                               sparse_indices=tuple(r["sparse_indices"] or ()), sparse_values=tuple(r["sparse_values"] or ()),
                               recorded_at=r["recorded_at"])


class SqlOutboxRepository(_Repo):
    def add(self, event: EventEnvelope, at: datetime) -> bool:
        with self._conflicts(f"outbox {event.event_id}"):
            got = self.ex.rows("INSERT INTO dm_outbox (event_id, topic, envelope, enqueued_at) VALUES (%s, %s, %s{JSONCAST}, %s) "
                               "ON CONFLICT DO NOTHING RETURNING event_id",
                               (event.event_id, event.topic, Json(event.model_dump(mode="json")), at))
        return bool(got)

    def pending(self, limit: int = 500) -> tuple[OutboxEntry, ...]:
        rows = self.ex.rows("SELECT event_id, topic, envelope, enqueued_at, published_at FROM dm_outbox WHERE published_at IS NULL "
                            "ORDER BY enqueued_at, event_id LIMIT %s", (int(limit),))
        return tuple(OutboxEntry(**{**r, "event_id": r["event_id"].strip(), "envelope": _json(r["envelope"])}) for r in rows)

    def mark_published(self, event_ids: tuple[str, ...], at: datetime) -> int:
        if not event_ids:
            return 0
        got = self.ex.rows(f"UPDATE dm_outbox SET published_at = %s WHERE published_at IS NULL AND event_id IN ({placeholders(len(event_ids))}) "
                           "RETURNING event_id", (at, *event_ids))
        return len(got)


class SqlUnitOfWork:
    """One transaction over one connection. Exiting without commit() rolls back."""

    def __init__(self, ex: SqlExecutor, release=None):
        self.ex, self._release = ex, release
        self.objects = SqlSourceObjectRepository(ex)
        self.graph = SqlGraphRepository(ex)
        self.aggregates = SqlAggregateRepository(ex)
        self.commands = SqlCommandLog(ex)
        self.stock = SqlStockRepository(ex)
        self.embeddings = SqlEmbeddingRepository(ex)
        self.outbox = SqlOutboxRepository(ex)
        self._done = False

    def __enter__(self):
        self.ex.begin()
        return self

    def __exit__(self, exc_type, exc, tb):
        try:
            if not self._done:
                self.ex.rollback()
        finally:
            if self._release:
                self._release(self.ex)

    def commit(self):
        self.ex.commit()
        self._done = True

    def rollback(self):
        self.ex.rollback()
        self._done = True


__all__ = ["SqlSourceObjectRepository", "SqlGraphRepository", "SqlAggregateRepository", "SqlCommandLog", "SqlStockRepository",
           "SqlEmbeddingRepository", "SqlOutboxRepository", "SqlUnitOfWork", "Decimal"]
