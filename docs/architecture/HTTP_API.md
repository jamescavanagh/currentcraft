---
title: HTTP API
version: 0.10.0
status: implementation in progress
tags: [datamesh, architecture, http]
---

# HTTP API Architecture (0.9.9 Intermediate Shell)

## Overview & Process Model
The HTTP API runs as a **separate operating system process** alongside the existing ingestion worker. It does not replace, wrap, or alter the verified `0.9.9` worker flow (`confirmed intake -> worker -> PostgreSQL object -> confirmed stored event`).

## Scope of This Slice
This initial shell slice intentionally implements **only**:
1. **Liveness (`GET /healthz`)**: Process-level health check. Performs **zero** database or message broker queries.
2. **Readiness (`GET /readyz`)**: Dependency probe verifying that configured downstream infrastructure (PostgreSQL and NATS JetStream) is reachable. If any required dependency is unavailable, `/readyz` returns `503 Service Unavailable`—it must never report false readiness.
3. **Authentication Check (`GET /v1/auth/check`)**: Protected endpoint verifying possession of the configured shared bearer secret.

Out of scope for this slice: document intake, simulation endpoints, HFGT endpoints, deletion, OIDC, and frontend assets.

## Intended Later Ingestion Flow
In subsequent slices, HTTP document intake will follow a strict asynchronous handoff:
`Blob Storage write -> Confirmed NATS JetStream publish -> Ingestion Worker -> PostgreSQL authoritative version store -> Confirmed stored event`.

## Authentication & Security Model
- **Shared Bearer Secret**: The protected endpoint uses HTTP Bearer authentication (`Authorization: Bearer <token>`) compared via constant-time digest (`secrets.compare_digest`).
- **Scope of Trust**: A valid bearer token authenticates **possession of a shared secret** only. It does **not** establish personal identity, role-based access control, or human approval authority.
- **Unresolved Identity Platform**: Long-term API identity and platform authentication (e.g., OIDC, mTLS, service-mesh identity) remain unresolved and are intentionally not decided by this shell.
- **Zero Secret Leakage**: Secrets must never appear in application logs, exception payloads, CLI arguments, generated OpenAPI schemas, or committed test fixtures.

## Startup, Lifespan & Failure Semantics
- **Fail-Fast Production Startup**: Missing required configuration (such as an empty or missing bearer token or database/broker DSNs in production mode) raises a startup configuration error and prevents the ASGI server from booting.
- **No Startup Side Effects**: The HTTP API **must not** execute database schema migrations (Alembic/DDL) or provision NATS JetStream streams/consumers during application import or lifespan startup.
- **Architectural Boundaries**:
  - FastAPI lives strictly under `app.interfaces.http`.
  - **Only** `app.interfaces.http.wiring` may import from `app.infrastructure`.
  - `app.domain` and `app.application` must never import FastAPI, `app.interfaces`, infrastructure drivers, NumPy, or PyTorch.

## Local Launch Instructions (Localhost-Only Binding)
During local development, always bind strictly to `127.0.0.1`:

```bash
# Install with the api extra
pip install -e ".[api]"

# Export required environment variables (or place in a non-committed .env file)
export DATAMESH_ENV="development"
export DATAMESH_API_BEARER_TOKEN="local-dev-secret-do-not-commit"
export DATAMESH_POSTGRES_DSN="postgresql://datamesh:datamesh@127.0.0.1:5432/datamesh"
export DATAMESH_NATS_URL="nats://127.0.0.1:4222"

# Launch uvicorn bound to localhost only
python -m uvicorn app.interfaces.http.app:create_app --factory --host 127.0.0.1 --port 8000
