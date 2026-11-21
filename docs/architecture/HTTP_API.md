---
title: HTTP API
version: 0.10.0
status: shell and privacy-safe read endpoints implemented; intake and live acceptance pending
tags: [currentcraft, architecture, http]
---

# HTTP API Architecture (0.10.0 read slice)

## Overview & Process Model
The HTTP API runs as a **separate operating system process** alongside the existing ingestion worker. It does not replace, wrap, or alter the verified `0.9.9` worker flow (`confirmed intake -> worker -> PostgreSQL object -> confirmed stored event`).

## Scope of This Slice
This shell slice intentionally implements **only**:
1. **Liveness (`GET /healthz`)**: Process-level health check. Performs **zero** database or message broker queries.
2. **Readiness (`GET /readyz`)**: Dependency probe verifying that configured downstream infrastructure (PostgreSQL and NATS JetStream) is reachable. If any required dependency is unavailable, `/readyz` returns `503 Service Unavailable`; it must never report false readiness.
3. **Authentication Check (`GET /v1/auth/check`)**: Protected endpoint verifying possession of the configured shared bearer secret.

Out of scope for this slice: document intake, simulation endpoints, HFGT endpoints, deletion, OIDC, and frontend assets.

The generated contract lives in [`docs/contracts/OPENAPI.json`](../contracts/OPENAPI.json) and is CI-gated by `scripts/gen_openapi.py --check`.

## Read endpoints (0.10.0)

The [HTTP document design](HTTP_DOCUMENTS.md) governs the four protected read
routes: document head, current/all-revision tasks, WBS JSON/CSV, and subject
lookup. Explicit DTOs withhold private source text, fields, evidence and
provenance. Opaque handles in bodies and URLs use a random server-only
process key, separate from authentication. Task occurrences are source
records, never approved work. Repository access runs in the threadpool and
never commits. Generated OpenAPI includes these routes.

Handles rotate on restart; private server-side integrations obtain initial
handles from the container codec. Subject URLs use the literal namespace
`opaque`, not a source namespace. Resolution fails closed at the documented
10,001-candidate ceiling; this is a local-alpha implementation, not a
persistent handle directory or public discovery service. WBS retains only
opaque structural codes, bounded levels, safe row kinds and a fixed source
label; other cells are withheld. Application error logs contain no request
paths or raw exceptions. Slash redirects are disabled so Location headers
cannot reflect supplied identifiers. Server/proxy access logs need separate
privacy configuration. Live database/API acceptance is not claimed.

## Intended Later Ingestion Flow
In subsequent slices (0.10.0), HTTP document intake will follow a strict asynchronous handoff:
`Blob Storage write -> Confirmed NATS JetStream publish -> Ingestion Worker -> PostgreSQL authoritative version store -> Confirmed stored event`.

## Authentication & Security Model
- **Shared Bearer Secret**: The protected endpoints use HTTP Bearer authentication (`Authorization: Bearer <token>`) compared via constant-time digest (`secrets.compare_digest`).
- **Scope of Trust**: A valid bearer token authenticates **possession of a shared secret** only. It does **not** establish personal identity, role-based access control, or human approval authority.
- **Unresolved Identity Platform**: Long-term API identity and platform authentication (e.g., OIDC, mTLS, service-mesh identity) remain unresolved and are intentionally not decided by this shell.
- **Zero Secret Leakage**: Secrets must never appear in application logs, exception payloads, CLI arguments, environment values, generated OpenAPI schemas, or committed test fixtures. Secrets are read from files, never from inline environment values.

## Configuration
Settings are loaded by `app.interfaces.http.settings.Settings.from_env`. Secret values are read from files whose paths are given in environment variables.

| Variable | Required | Default | Meaning |
| --- | --- | --- | --- |
| `DATAMESH_API_TOKEN_FILE` | yes | none | Path to the file holding the shared bearer secret |
| `DATAMESH_NATS_TOKEN_FILE` | yes | none | Path to the file holding the NATS token |
| `DATAMESH_NATS_SERVERS` | no | `nats://127.0.0.1:4222` | Comma-separated NATS server URLs |
| `DATAMESH_PG_DSN` | one of | none | Full PostgreSQL DSN; when set, the host/port/database/user variables are ignored |
| `DATAMESH_PG_APP_FILE` | one of | none | Path to the file holding the application database password (used when no DSN is given) |
| `DATAMESH_PG_HOST` | no | `127.0.0.1` | PostgreSQL host |
| `DATAMESH_PG_PORT` | no | `5433` | PostgreSQL port (the local Compose stack's host port) |
| `DATAMESH_PG_DATABASE` | no | `datamesh` | Database name |
| `DATAMESH_PG_USER` | no | `datamesh_app` | Database user |
| `DATAMESH_DEPENDENCY_TIMEOUT_SECONDS` | no | `3.0` | Per-dependency readiness timeout |

The `DATAMESH_` prefix and database names predate the Currentcraft rename; renaming them is part of the 0.10.0 release, with the old names accepted for one release.

## Startup, Lifespan & Failure Semantics
- **Fail-Fast Startup**: Missing, unreadable, or empty required configuration raises a configuration error that names the setting without its value, and the API does not start.
- **No Startup Side Effects**: The HTTP API **must not** execute database schema migrations (Alembic/DDL) or provision NATS JetStream streams/consumers during application import or lifespan startup.
- **Architectural Boundaries**:
  - FastAPI lives strictly under `app.interfaces.http`.
  - **Only** `app.interfaces.http.wiring` may import from `app.infrastructure`.
  - `app.domain` and `app.application` must never import FastAPI, `app.interfaces`, infrastructure drivers, NumPy, or PyTorch.

## Local Launch Instructions (Localhost-Only Binding)
During local development, always bind strictly to `127.0.0.1`. Keep secret files outside the repository (or under the git-ignored `local/` directory) with owner-only permissions.

```bash
# Install with the api extra
pip install -e ".[api]"

# Point the API at secret files (never put secret values in environment variables)
export DATAMESH_API_TOKEN_FILE="$PWD/local/compose-secrets/api_token"
export DATAMESH_NATS_TOKEN_FILE="$PWD/local/compose-secrets/nats_token"
export DATAMESH_PG_APP_FILE="$PWD/local/compose-secrets/pg_app"
export DATAMESH_NATS_SERVERS="nats://127.0.0.1:4222"

# Launch uvicorn bound to localhost only
python -m uvicorn app.interfaces.http.app:create_app --factory --host 127.0.0.1 --port 8000
```

The local Compose stack generates `nats_token` and `pg_app`; it does not yet generate `api_token` (that arrives with the 0.10.0 Compose service). Create it yourself, for example `python -c "import secrets; print(secrets.token_hex(32))" > local/compose-secrets/api_token`, then restrict it with `chmod 600`.
