"""Thin executor over a DB-API connection with conn.execute() (psycopg 3, duckdb). Explicit transactions."""

from __future__ import annotations

from typing import Any, Sequence

from .dialect import Dialect


class SqlExecutor:
    """Runs rendered statements with bound parameters. The connection must be in autocommit mode: this class owns
    BEGIN / COMMIT / ROLLBACK so every unit of work is one explicit transaction."""

    def __init__(self, conn, dialect: Dialect):
        self.conn, self.dialect = conn, dialect
        self._cache: dict[str, str] = {}
        self.in_tx = False

    def _sql(self, template: str) -> str:
        s = self._cache.get(template)
        if s is None:
            s = self._cache[template] = self.dialect.render(template)
        return s

    def rows(self, template: str, params: Sequence[Any] = ()) -> list[dict]:
        cur = self.conn.execute(self._sql(template), [self.dialect.to_db(p) for p in params])
        if cur is None or cur.description is None:
            return []
        names = [d[0] for d in cur.description]
        return [{n: self.dialect.from_db(v) for n, v in zip(names, row)} for row in cur.fetchall()]

    def run(self, template: str, params: Sequence[Any] = ()) -> None:
        self.conn.execute(self._sql(template), [self.dialect.to_db(p) for p in params])

    def begin(self):
        if self.in_tx:
            raise RuntimeError("nested transaction")
        self.conn.execute(self.dialect.begin_sql)
        self.in_tx = True

    def commit(self):
        self.conn.execute("COMMIT")
        self.in_tx = False

    def rollback(self):
        if self.in_tx:
            try:
                self.conn.execute("ROLLBACK")
            finally:
                self.in_tx = False


def placeholders(n: int) -> str:
    """'%s, %s, ...' for an IN list of n bound values (n >= 1)."""
    if n < 1:
        raise ValueError("empty IN list")
    return ", ".join(["%s"] * n)
