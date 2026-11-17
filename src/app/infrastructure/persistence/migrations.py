"""Schema migrations. Ordered, idempotent, recorded in dm_schema_migrations. PostgreSQL 18 is the target.

Migration 101 (pgvector columns) is opt-in and PostgreSQL-only: it needs CREATE EXTENSION rights.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from .dialect import Dialect
from .sql import SqlExecutor


@dataclass(frozen=True)
class Migration:
    version: int
    name: str
    statements: tuple[str, ...]
    postgres_only: bool = False
    opt_in: bool = False


BOOTSTRAP = ("CREATE TABLE IF NOT EXISTS dm_schema_migrations (version INTEGER PRIMARY KEY, name TEXT NOT NULL, "
             "applied_at {TS} NOT NULL)")

MIGRATIONS = (
    Migration(1, "source objects, heads and edges", (
        "CREATE TABLE IF NOT EXISTS dm_source_objects ("
        " object_id TEXT NOT NULL, version_no INTEGER NOT NULL CHECK (version_no >= 1), kind TEXT NOT NULL,"
        " digest CHAR(64) NOT NULL, content_sha256 CHAR(64) NOT NULL, adapter TEXT NOT NULL, adapter_version TEXT NOT NULL,"
        " body {JSON} NOT NULL, received_at {TS} NOT NULL, stored_at {TS} NOT NULL,"
        " PRIMARY KEY (object_id, version_no))",
        "CREATE TABLE IF NOT EXISTS dm_source_object_heads ("
        " object_id TEXT PRIMARY KEY, version_no INTEGER NOT NULL, kind TEXT NOT NULL, digest CHAR(64) NOT NULL)",
        "CREATE INDEX IF NOT EXISTS dm_heads_kind ON dm_source_object_heads (kind)",
        "CREATE TABLE IF NOT EXISTS dm_edges ("
        " src_id TEXT NOT NULL, src_version INTEGER NOT NULL, ordinal INTEGER NOT NULL, rel_type TEXT NOT NULL,"
        " dst_id TEXT NOT NULL, evidence TEXT NOT NULL, PRIMARY KEY (src_id, src_version, ordinal))",
        "CREATE INDEX IF NOT EXISTS dm_edges_dst ON dm_edges (dst_id, rel_type)",
        "CREATE INDEX IF NOT EXISTS dm_edges_src ON dm_edges (src_id, rel_type)",
    )),
    Migration(2, "versioned aggregates and command log", (
        "CREATE TABLE IF NOT EXISTS dm_aggregates ("
        " aggregate_type TEXT NOT NULL, aggregate_id {UUID} NOT NULL, version INTEGER NOT NULL CHECK (version >= 1),"
        " schema_version TEXT NOT NULL, payload {JSON} NOT NULL, recorded_at {TS} NOT NULL, command_id TEXT,"
        " PRIMARY KEY (aggregate_type, aggregate_id))",
        "CREATE TABLE IF NOT EXISTS dm_aggregate_versions ("
        " aggregate_type TEXT NOT NULL, aggregate_id {UUID} NOT NULL, version INTEGER NOT NULL,"
        " schema_version TEXT NOT NULL, payload {JSON} NOT NULL, recorded_at {TS} NOT NULL, command_id TEXT,"
        " PRIMARY KEY (aggregate_type, aggregate_id, version))",
        "CREATE TABLE IF NOT EXISTS dm_commands ("
        " command_id TEXT PRIMARY KEY, command_type TEXT NOT NULL, outcome TEXT NOT NULL CHECK (outcome IN ('applied', 'rejected')),"
        " result_ref TEXT, detail TEXT, recorded_at {TS} NOT NULL)",
    )),
    Migration(3, "shared stock and reservations", (
        "CREATE TABLE IF NOT EXISTS dm_stock_positions ("
        " stock_id TEXT PRIMARY KEY, item_ref TEXT NOT NULL, uom TEXT NOT NULL,"
        " on_hand {NUM} NOT NULL CHECK (on_hand >= 0), reserved {NUM} NOT NULL DEFAULT 0 CHECK (reserved >= 0),"
        " version INTEGER NOT NULL DEFAULT 1, CHECK (reserved <= on_hand))",
        "CREATE TABLE IF NOT EXISTS dm_reservations ("
        " reservation_id {UUID} PRIMARY KEY, stock_id TEXT NOT NULL {FK_STOCK}, claimant_ref TEXT NOT NULL,"
        " quantity {NUM} NOT NULL CHECK (quantity > 0), status TEXT NOT NULL CHECK (status IN ('active', 'released')),"
        " command_id TEXT NOT NULL UNIQUE, created_at {TS} NOT NULL, released_at {TS}, release_command_id TEXT)",
        "CREATE INDEX IF NOT EXISTS dm_reservations_stock ON dm_reservations (stock_id, status)",
    )),
    Migration(4, "embeddings", (
        "CREATE TABLE IF NOT EXISTS dm_embeddings ("
        " object_id TEXT NOT NULL, model_name TEXT NOT NULL, model_version TEXT NOT NULL, dim INTEGER NOT NULL CHECK (dim > 0),"
        " float_precision TEXT NOT NULL CHECK (float_precision IN ('float32', 'float64')), dense {F8ARR}, dense_mask {BOOLARR},"
        " sparse_indices {I4ARR}, sparse_values {F8ARR}, recorded_at {TS} NOT NULL,"
        " PRIMARY KEY (object_id, model_name, model_version))",
    )),
    Migration(5, "transactional outbox", (
        "CREATE TABLE IF NOT EXISTS dm_outbox ("
        " event_id CHAR(64) PRIMARY KEY, topic TEXT NOT NULL, envelope {JSON} NOT NULL, enqueued_at {TS} NOT NULL,"
        " published_at {TS})",
        "CREATE INDEX IF NOT EXISTS dm_outbox_pending ON dm_outbox (enqueued_at) {PENDING_WHERE}",
    )),
    Migration(101, "pgvector columns (opt-in)", (
        "CREATE EXTENSION IF NOT EXISTS vector",
        "ALTER TABLE dm_embeddings ADD COLUMN IF NOT EXISTS dense_vec vector",
        "ALTER TABLE dm_embeddings ADD COLUMN IF NOT EXISTS sparse_vec sparsevec",
    ), postgres_only=True, opt_in=True),
)


def applicable(dialect: Dialect, include_opt_in: bool = False) -> tuple[Migration, ...]:
    return tuple(m for m in MIGRATIONS if (not m.postgres_only or dialect.name == "postgresql") and (include_opt_in or not m.opt_in))


def migrate(ex: SqlExecutor, include_opt_in: bool = False) -> list[int]:
    """Apply missing migrations, one transaction each. Returns the versions applied now."""
    ex.run(BOOTSTRAP)
    done = {r["version"] for r in ex.rows("SELECT version FROM dm_schema_migrations")}
    applied = []
    for m in applicable(ex.dialect, include_opt_in):
        if m.version in done:
            continue
        ex.begin()
        try:
            for stmt in m.statements:
                ex.run(stmt)
            ex.run("INSERT INTO dm_schema_migrations (version, name, applied_at) VALUES (%s, %s, %s)",
                   (m.version, m.name, datetime.now(timezone.utc)))
            ex.commit()
        except Exception:
            ex.rollback()
            raise
        applied.append(m.version)
    return applied


def render_ddl(dialect: Dialect, include_opt_in: bool = True) -> str:
    """The schema as SQL for one dialect (used to generate docs)."""
    out = [dialect.render(BOOTSTRAP) + ";"]
    for m in applicable(dialect, include_opt_in):
        out.append(f"-- {m.version:03d} {m.name}")
        out += [dialect.render(s) + ";" for s in m.statements]
    return "\n".join(out) + "\n"
