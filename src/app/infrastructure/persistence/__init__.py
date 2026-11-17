"""Persistence adapters: PostgreSQL 18 repositories (SQL), a DuckDB test stand-in, and in-memory repositories."""

from .dialect import DUCKDB_STANDIN, POSTGRES, Dialect, with_pgvector  # noqa: F401
from .memory import MemoryStore, MemoryUnitOfWork  # noqa: F401
from .migrations import MIGRATIONS, migrate, render_ddl  # noqa: F401
from .repositories import SqlUnitOfWork  # noqa: F401
from .vectors import dense_literal, parse_sparse, sparse_literal  # noqa: F401
from .wiring import SqlUnitOfWorkFactory, build_duckdb_standin, build_memory, build_postgres  # noqa: F401
