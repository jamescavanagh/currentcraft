"""Infrastructure wiring for the HTTP API shell.

This is the only module under app.interfaces permitted to import app.infrastructure.
"""

from __future__ import annotations

import asyncio
import math
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from app.infrastructure.messaging import connect_jetstream
from app.infrastructure.persistence import build_postgres

from .container import Container
from .settings import Settings


class StartupWiringError(RuntimeError):
    """Sanitized startup failure that never exposes DSNs, paths, or credentials."""


def _apply_pg_connect_timeout(pg_dsn: str, timeout_seconds: float) -> str:
    """Apply libpq connect_timeout (integer seconds >= 1) safely to URI or key=value conninfo."""
    timeout_int = max(1, int(math.ceil(timeout_seconds)))
    stripped = pg_dsn.strip()
    if stripped.startswith(("postgresql://", "postgres://")):
        parts = urlsplit(stripped)
        query_items = [
            (k, v)
            for k, v in parse_qsl(parts.query, keep_blank_values=True)
            if k != "connect_timeout"
        ]
        query_items.append(("connect_timeout", str(timeout_int)))
        return urlunsplit(
            (parts.scheme, parts.netloc, parts.path, urlencode(query_items), parts.fragment)
        )
    if "connect_timeout=" in stripped:
        return stripped
    return f"{stripped} connect_timeout={timeout_int}"


async def _close_broker_safely(broker: object, timeout: float) -> None:
    """Close or drain the JetStream broker within a bounded timeout."""
    close_fn = getattr(broker, "close", None)
    if callable(close_fn):
        try:
            result = close_fn()
            if asyncio.iscoroutine(result):
                await asyncio.wait_for(result, timeout=timeout)
            return
        except Exception:
            pass

    nc = (
        getattr(broker, "nc", None)
        or getattr(broker, "connection", None)
        or getattr(broker, "_nc", None)
    )
    if nc is not None:
        for method_name in ("drain", "close"):
            fn = getattr(nc, method_name, None)
            if callable(fn):
                try:
                    await asyncio.wait_for(fn(), timeout=timeout)
                    return
                except Exception:
                    continue


async def build_container(settings: Settings) -> Container:
    """Build the runtime Container without running migrations or provisioning streams."""
    timeout = settings.dependency_timeout_seconds
    bounded_dsn = _apply_pg_connect_timeout(settings.pg_dsn, timeout)

    uow_factory = None
    broker = None
    try:
        try:
            uow_factory = build_postgres(bounded_dsn, run_migrations=False)
        except TypeError:
            uow_factory = build_postgres(dsn=bounded_dsn, run_migrations=False)

        broker = await asyncio.wait_for(
            connect_jetstream(
                servers=settings.nats_servers,
                token=settings.nats_token,
            ),
            timeout=timeout,
        )
    except Exception:
        if broker is not None:
            await _close_broker_safely(broker, timeout=timeout)
        if uow_factory is not None:
            close_uow = getattr(uow_factory, "close", None)
            if callable(close_uow):
                try:
                    res = close_uow()
                    if asyncio.iscoroutine(res):
                        await res
                except Exception:
                    pass
        raise StartupWiringError(
            "Failed to initialize HTTP API infrastructure dependencies."
        ) from None

    def _sync_db_probe() -> bool:
        with uow_factory() as uow:
            uow.commands.get("readiness-probe")
        return True

    async def database_ready() -> bool:
        try:
            return await asyncio.wait_for(
                asyncio.to_thread(_sync_db_probe),
                timeout=timeout,
            )
        except Exception:
            return False

    async def broker_ready() -> bool:
        try:
            nc = (
                getattr(broker, "nc", None)
                or getattr(broker, "connection", None)
                or getattr(broker, "_nc", None)
                or broker
            )
            is_connected = getattr(nc, "is_connected", True)
            if callable(is_connected):
                is_connected = is_connected()
            if not is_connected:
                return False

            flush_fn = getattr(nc, "flush", None)
            if callable(flush_fn):
                await asyncio.wait_for(flush_fn(timeout=timeout), timeout=timeout)
                return True

            ping_fn = getattr(broker, "ping", None)
            if callable(ping_fn):
                res = ping_fn()
                if asyncio.iscoroutine(res):
                    await asyncio.wait_for(res, timeout=timeout)
                return True

            return bool(is_connected)
        except Exception:
            return False

    async def close() -> None:
        await _close_broker_safely(broker, timeout=timeout)
        close_uow = getattr(uow_factory, "close", None)
        if callable(close_uow):
            try:
                res = close_uow()
                if asyncio.iscoroutine(res):
                    await asyncio.wait_for(res, timeout=timeout)
            except Exception:
                pass

    return Container(
        settings=settings,
        database_ready=database_ready,
        broker_ready=broker_ready,
        close=close,
    )
