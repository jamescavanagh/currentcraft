"""Composition: build a unit-of-work factory for PostgreSQL 18, the DuckDB test stand-in, or memory.

Only this module touches drivers. psycopg is imported lazily (pip install 'datamesh-agency-toolkit[postgres]').
"""

from __future__ import annotations

import threading
from typing import Callable

from .dialect import DUCKDB_STANDIN, POSTGRES, Dialect, with_pgvector
from .memory import MemoryStore
from .migrations import migrate
from .repositories import SqlUnitOfWork
from .sql import SqlExecutor


class SqlUnitOfWorkFactory:
    """Each call opens one unit of work on a connection from `connect`. Connections must be autocommit."""

    def __init__(self, connect: Callable[[], object], dialect: Dialect, close: Callable[[object], None] | None = None):
        self._connect, self.dialect, self._close = connect, dialect, close

    def executor(self) -> SqlExecutor:
        return SqlExecutor(self._connect(), self.dialect)

    def __call__(self) -> SqlUnitOfWork:
        ex = self.executor()
        return SqlUnitOfWork(ex, release=(lambda e: self._close(e.conn)) if self._close else None)

    def migrate(self, include_opt_in: bool = False) -> list[int]:
        ex = self.executor()
        try:
            return migrate(ex, include_opt_in or self.dialect.pgvector)
        finally:
            if self._close:
                self._close(ex.conn)


def build_postgres(dsn: str, pgvector: bool = False, run_migrations: bool = True) -> SqlUnitOfWorkFactory:
    """PostgreSQL 18 via psycopg 3. One connection per unit of work; put a pool (e.g. psycopg_pool) behind `connect`
    for production. pgvector=True also writes vector/sparsevec columns (migration 101 needs CREATE EXTENSION)."""
    try:
        import psycopg  # noqa: PLC0415  (lazy: optional extra)
    except ImportError as e:  # pragma: no cover - environment dependent
        raise RuntimeError("PostgreSQL support needs psycopg 3: pip install 'datamesh-agency-toolkit[postgres]'") from e
    dialect = with_pgvector(POSTGRES) if pgvector else POSTGRES
    f = SqlUnitOfWorkFactory(lambda: psycopg.connect(dsn, autocommit=True), dialect, close=lambda c: c.close())
    if run_migrations:
        f.migrate()
    return f


def build_duckdb_standin(path: str = ":memory:", run_migrations: bool = True) -> SqlUnitOfWorkFactory:
    """Test stand-in: runs the same statements on DuckDB. Not evidence of PostgreSQL compatibility.
    One shared connection, serialized by a lock (DuckDB has no row-level FOR UPDATE)."""
    import duckdb  # noqa: PLC0415

    conn = duckdb.connect(path)
    lock = threading.RLock()

    def connect():
        lock.acquire()
        return conn

    f = SqlUnitOfWorkFactory(connect, DUCKDB_STANDIN, close=lambda c: lock.release())
    f.raw_connection = conn  # for tests
    if run_migrations:
        f.migrate()
    return f


def build_memory() -> MemoryStore:
    return MemoryStore()


__all__ = ["SqlUnitOfWorkFactory", "build_postgres", "build_duckdb_standin", "build_memory"]
