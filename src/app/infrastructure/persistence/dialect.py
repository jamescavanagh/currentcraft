"""SQL dialects. PostgreSQL 18 is the target; the DuckDB stand-in only executes the same statements in tests.

Statements are written once with %s placeholders and {TOKENS} for types that differ. Values are always bound
parameters; tokens are fixed type names from this module, never data.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone

_TOKEN = re.compile(r"\{([A-Z_0-9]+)\}")


@dataclass(frozen=True)
class Json:
    """Marks a bound parameter as JSON (dict/list, or an already-serialized string)."""
    value: object


@dataclass(frozen=True)
class Dialect:
    name: str
    placeholder: str
    tokens: dict = field(default_factory=dict)
    begin_sql: str = "BEGIN"
    naive_utc: bool = False          # store timestamps as naive UTC (stand-in has no tz-aware fetch without pytz)
    pgvector: bool = False           # write pgvector columns too (needs migration 101 and the extension)
    conflict_names: tuple = ("UniqueViolation", "IntegrityError", "ConstraintException", "CheckViolation",
                             "ForeignKeyViolation", "SerializationFailure", "DeadlockDetected", "TransactionException")

    def render(self, template: str) -> str:
        sql = _TOKEN.sub(lambda m: self.tokens[m.group(1)], template)
        return sql if self.placeholder == "%s" else sql.replace("%s", self.placeholder)

    def to_db(self, v):
        if isinstance(v, datetime):
            if v.tzinfo is None:
                raise ValueError("timestamps must be timezone-aware")
            return v.astimezone(timezone.utc).replace(tzinfo=None) if self.naive_utc else v
        if isinstance(v, Json):
            return v.value if isinstance(v.value, str) else json.dumps(v.value, sort_keys=True, separators=(",", ":"))
        if isinstance(v, tuple):
            return list(v)
        return v

    def from_db(self, v):
        if isinstance(v, datetime) and v.tzinfo is None:
            return v.replace(tzinfo=timezone.utc)
        return v

    def is_conflict(self, exc: BaseException) -> bool:
        return any(c.__name__ in self.conflict_names for c in type(exc).__mro__)


POSTGRES = Dialect(
    name="postgresql",
    placeholder="%s",
    tokens={"JSON": "JSONB", "JSONCAST": "::jsonb", "TS": "TIMESTAMPTZ", "NUM": "NUMERIC(38,12)", "UUID": "UUID",
            "F8ARR": "DOUBLE PRECISION[]", "I4ARR": "INTEGER[]", "BOOLARR": "BOOLEAN[]",
            "FK_STOCK": "REFERENCES dm_stock_positions (stock_id)", "SKIP_LOCKED": "FOR UPDATE SKIP LOCKED",
            "PENDING_WHERE": "WHERE published_at IS NULL"},
    begin_sql="BEGIN ISOLATION LEVEL READ COMMITTED",
)

# Test stand-in only: proves statements run and semantics hold, not PostgreSQL compatibility.
DUCKDB_STANDIN = Dialect(
    name="duckdb-standin",
    placeholder="?",
    tokens={"JSON": "JSON", "JSONCAST": "::JSON", "TS": "TIMESTAMP", "NUM": "DECIMAL(38,12)", "UUID": "UUID",
            "F8ARR": "DOUBLE[]", "I4ARR": "INTEGER[]", "BOOLARR": "BOOLEAN[]",
            "FK_STOCK": "", "SKIP_LOCKED": "", "PENDING_WHERE": ""},
    begin_sql="BEGIN TRANSACTION",
    naive_utc=True,
)


def with_pgvector(d: Dialect) -> Dialect:
    if d.name != "postgresql":
        raise ValueError("pgvector columns exist only on PostgreSQL")
    return Dialect(d.name, d.placeholder, dict(d.tokens), d.begin_sql, d.naive_utc, True, d.conflict_names)
