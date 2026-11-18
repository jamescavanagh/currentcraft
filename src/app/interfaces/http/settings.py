"""Environment and file-based configuration for the Currentcraft HTTP API shell."""

from __future__ import annotations

import math
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Mapping
from urllib.parse import quote


class SettingsError(ValueError):
    """Configuration error that identifies the setting name without leaking values."""


def _read_required_secret_file(var_name: str, raw_path: str | None) -> str:
    """Read a required secret file, failing safely if unset, unreadable, or empty."""
    if raw_path is None or not raw_path.strip():
        raise SettingsError(f"Required configuration variable {var_name} is not set.")

    path = Path(raw_path.strip())
    try:
        if not path.is_file():
            raise SettingsError(f"Configuration file for {var_name} is not a readable file.")
        content = path.read_text(encoding="utf-8").strip()
    except OSError as exc:
        raise SettingsError(f"Configuration file for {var_name} could not be read.") from exc

    if not content:
        raise SettingsError(f"Configuration file for {var_name} must not be empty.")

    return content


def _parse_port(var_name: str, raw_port: str) -> int:
    try:
        port = int(raw_port.strip())
    except ValueError as exc:
        raise SettingsError(f"Invalid integer value for {var_name}.") from exc
    if not (1 <= port <= 65535):
        raise SettingsError(f"Port in {var_name} must be between 1 and 65535.")
    return port


def _parse_timeout(var_name: str, raw_timeout: str) -> float:
    try:
        timeout = float(raw_timeout.strip())
    except ValueError as exc:
        raise SettingsError(f"Invalid numeric value for {var_name}.") from exc
    if not math.isfinite(timeout) or timeout <= 0.0:
        raise SettingsError(f"Timeout in {var_name} must be a finite number greater than 0.")
    return timeout


def _build_pg_dsn(env: Mapping[str, str]) -> str:
    explicit_dsn_raw = env.get("DATAMESH_PG_DSN")
    if explicit_dsn_raw is not None:
        explicit_dsn = explicit_dsn_raw.strip()
        if not explicit_dsn:
            raise SettingsError("DATAMESH_PG_DSN must not be empty when explicitly provided.")
        if "DATAMESH_PG_APP_FILE" in env and env["DATAMESH_PG_APP_FILE"].strip():
            _read_required_secret_file("DATAMESH_PG_APP_FILE", env.get("DATAMESH_PG_APP_FILE"))
        return explicit_dsn

    password = _read_required_secret_file(
        "DATAMESH_PG_APP_FILE", env.get("DATAMESH_PG_APP_FILE")
    )
    host = env.get("DATAMESH_PG_HOST", "127.0.0.1").strip()
    if not host:
        raise SettingsError("DATAMESH_PG_HOST must not be empty.")

    port = _parse_port("DATAMESH_PG_PORT", env.get("DATAMESH_PG_PORT", "5433"))

    database = env.get("DATAMESH_PG_DATABASE", "datamesh").strip()
    if not database:
        raise SettingsError("DATAMESH_PG_DATABASE must not be empty.")

    user = env.get("DATAMESH_PG_USER", "datamesh_app").strip()
    if not user:
        raise SettingsError("DATAMESH_PG_USER must not be empty.")

    encoded_user = quote(user, safe="")
    encoded_password = quote(password, safe="")
    encoded_db = quote(database, safe="")
    host_literal = f"[{host}]" if ":" in host and not host.startswith("[") else host

    return f"postgresql://{encoded_user}:{encoded_password}@{host_literal}:{port}/{encoded_db}"


def _parse_nats_servers(raw_servers: str) -> tuple[str, ...]:
    if not raw_servers or not raw_servers.strip():
        raise SettingsError("DATAMESH_NATS_SERVERS must not be empty.")
    parts = [part.strip() for part in raw_servers.split(",")]
    if not parts or any(not part for part in parts):
        raise SettingsError("DATAMESH_NATS_SERVERS must not contain empty server entries.")
    return tuple(parts)


@dataclass(frozen=True)
class Settings:
    """Immutable HTTP API settings with secret fields excluded from repr."""

    pg_dsn: str = field(repr=False)
    nats_servers: tuple[str, ...]
    nats_token: str = field(repr=False)
    api_token: str = field(repr=False)
    dependency_timeout_seconds: float = 3.0

    @classmethod
    def from_env(cls, environ: Mapping[str, str] | None = None) -> Settings:
        """Load and validate configuration from environment variables and secret files."""
        env = os.environ if environ is None else environ

        api_token = _read_required_secret_file(
            "DATAMESH_API_TOKEN_FILE", env.get("DATAMESH_API_TOKEN_FILE")
        )
        nats_token = _read_required_secret_file(
            "DATAMESH_NATS_TOKEN_FILE", env.get("DATAMESH_NATS_TOKEN_FILE")
        )
        pg_dsn = _build_pg_dsn(env)

        raw_servers = env.get("DATAMESH_NATS_SERVERS", "nats://127.0.0.1:4222")
        nats_servers = _parse_nats_servers(raw_servers)

        timeout = _parse_timeout(
            "DATAMESH_DEPENDENCY_TIMEOUT_SECONDS",
            env.get("DATAMESH_DEPENDENCY_TIMEOUT_SECONDS", "3.0"),
        )

        return cls(
            pg_dsn=pg_dsn,
            nats_servers=nats_servers,
            nats_token=nats_token,
            api_token=api_token,
            dependency_timeout_seconds=timeout,
        )
