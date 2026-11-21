---
title: HTTP API
version: 0.9.9
status: shell implemented; nonroot Compose API and secret provisioner; live acceptance pending
tags: [currentcraft, architecture, http]
---

# HTTP API Architecture (0.9.9 Shell)

## Overview & Process Model
The HTTP API runs as a **separate operating system process** alongside the existing ingestion worker. It does not replace, wrap, or alter the verified `0.9.9` worker flow (`confirmed intake -> worker -> PostgreSQL object -> confirmed stored event`).

## Scope of This Slice
This shell slice intentionally implements **only**:
1. **Liveness (`GET /healthz`)**: Process-level health check. Performs **zero** database or message broker queries.
2. **Readiness (`GET /readyz`)**: Dependency probe verifying that configured downstream infrastructure (PostgreSQL and NATS JetStream) is reachable. If any required dependency is unavailable, `/readyz` returns `503 Service Unavailable`; it must never report false readiness.
3. **Authentication Check (`GET /v1/auth/check`)**: Protected endpoint verifying possession of the configured shared bearer secret.

Out of scope for this slice: document intake, simulation endpoints, HFGT endpoints, deletion, OIDC, and frontend assets.

The generated contract lives in [`docs/contracts/OPENAPI.json`](../contracts/OPENAPI.json) and is CI-gated by `scripts/gen_openapi.py --check`.

## Intended Later Ingestion Flow
In subsequent slices (0.10.0), HTTP document intake will follow a strict asynchronous handoff:
`Blob Storage write -> Confirmed NATS JetStream publish -> Ingestion Worker -> PostgreSQL authoritative version store -> Confirmed stored event`.

## Authentication & Security Model
- **Shared Bearer Secret**: The protected endpoint uses HTTP Bearer authentication (`Authorization: Bearer <token>`) compared via constant-time digest (`secrets.compare_digest`).
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

The local stack launcher and `deploy/local/runtime.py` accept `CURRENTCRAFT_*` as
the preferred configuration prefix, with `DATAMESH_*` accepted for one release.
An explicitly supplied preferred name wins, including an empty value (which
must not silently revive a legacy value). At process launch, the runtime bridges
preferred settings into the legacy names still consumed by the HTTP settings
module. Direct uvicorn invocation does not install this bridge. This is not a
repository-wide rename: database names, persisted identities, images, volume
names and protected HTTP/ingestion code remain unchanged.

Compose host port overrides are `CURRENTCRAFT_API_PORT` (8000),
`CURRENTCRAFT_PG_PORT` (5433), and `CURRENTCRAFT_NATS_PORT` (4222), each with the
matching legacy fallback. PostgreSQL's container port stays 5432. Configuration
contains paths, never inline API/NATS/password values.

## Startup, Lifespan & Failure Semantics
- **Fail-Fast Startup**: Missing, unreadable, or empty required configuration raises a configuration error that names the setting without its value, and the API does not start.
- **No Startup Side Effects**: The HTTP API **must not** execute database schema migrations (Alembic/DDL) or provision NATS JetStream streams/consumers during application import or lifespan startup.
- **Architectural Boundaries**:
  - FastAPI lives strictly under `app.interfaces.http`.
  - **Only** `app.interfaces.http.wiring` may import from `app.infrastructure`.
  - `app.domain` and `app.application` must never import FastAPI, `app.interfaces`, infrastructure drivers, NumPy, or PyTorch.

## Local Launch Instructions (Localhost-Only Publishing)

The API is a separate process from the worker. `prepare` initializes shared
volumes; `bootstrap` alone performs migrations and stream provisioning. The
API waits for successful bootstrap and starts uvicorn as UID/GID 10001, with
the API extra installed. Both the API and the new secret-provisioning container
start as UID/GID 10001, drop all capabilities and enable no-new-privileges.
Neither starts as root, changes ownership or drops privileges at runtime.
The API healthcheck requires `/readyz` to return 200.

The container listener binds to `0.0.0.0:8000` so Docker can forward traffic,
but the published host address is strictly `127.0.0.1`. This is container
reachability, not permission to expose the API on host network interfaces.
Non-container listeners must bind to `127.0.0.1`.

```bash
python3 scripts/local_stack.py init
python3 scripts/local_stack.py up
python3 scripts/local_stack.py api-smoke
```

`init` creates `api_token` exclusively with 64 lowercase hex characters and
owner-only mode 0600 in git-ignored `local/compose-secrets/`. It retains and
validates existing secrets, refuses symlinks, and never prints their values.
Other pre-existing stack secrets keep their existing modes and identities.
Compose file-backed secrets do not reliably remap file ownership. Instead,
the host launcher builds the application image, then streams only the three
validated API dependencies (`api_token`, `pg_app`, `nats_token`) as bounded JSON
over stdin to the nonroot `api-secrets` provisioning container. No secret
value goes in argv or environment, and provisioning output is captured rather
than echoed. Provisioning failure prevents the launcher from starting the API.

The image initializes `/run/currentcraft-secrets` as UID/GID 10001, mode 0700
at build time. Docker initializes the new `api_secrets` named volume from
that directory. The provisioner alone mounts it writable; the API mounts it
read-only and has no host secret mounts. Files are atomically installed with
mode 0400 and verified owner/group. Existing matching files are retained;
symlinks, wrong permissions, malformed input and mismatched existing values
fail closed without silently rotating anything. A partial initial provision
can be retried: already-installed matching files remain valid.

The API validates its exact runtime UID/GID and private secret directory/files
before exec. Starting it directly with Compose requires prior provisioning;
an empty or incorrectly owned volume fails closed. The host API token is
never made world-readable. The new volume persists with `down`, contains
secrets and must not be exported or published. Credential rotation/recovery
needs an explicit operator procedure, not automatic overwrite.

This makes the API and its new provisioner nonroot, not the entire stack:
the existing root `prepare` service is unchanged. It does not establish
Docker daemon rootless mode. Actual volume ownership and startup behavior
still require Docker acceptance evidence.

`api-smoke` starts the stack and polls shell endpoints within a bounded
deadline: `/healthz` and `/readyz` must return 200; `/v1/auth/check` must reject
missing and incorrect tokens (401) and accept the generated token (200).
Only generic results are printed. Credentials stay out of argv, environment
values, HTTP response output and redirects. `smoke` also retains the existing
worker-to-PostgreSQL-to-stored-event smoke. POST-and-poll document intake is
deferred until the intake endpoints land; shell success is not intake acceptance.

Acceptance requires static service/configuration and token-security tests,
both naming schemes and precedence tests, nonroot provisioning/launch tests, and
bounded positive/negative shell smoke tests. Actual Docker acceptance and
live dependency compatibility must be reported separately from static checks.
The shared-token JetStream connector prerequisite must land before live API
startup can pass; this integration does not change its protected dependencies.
