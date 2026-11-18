cd ~/Apps/currentcraft

cat << 'EOF' > README.md
# Currentcraft (`datamesh-agency-toolkit`)

Currentcraft is an open-source cyber-physical data mesh and event-driven state toolkit (`0.9.9`). It pairs a clean hexagonal architecture with append-only versioned persistence in PostgreSQL, durable NATS JetStream event streaming, hetero-functional graph topology modeling, and a lifespan-managed FastAPI HTTP shell.

---

## Architecture & Repository Layout

Currentcraft enforces strict dependency boundaries across four layers (verified via AST layering tests in `tests/test_http_layering.py`):

* **`src/app/domain/`** — Pure domain entities, immutable versioning contracts, and topological invariants. Zero external framework, driver, or numerical library imports.
* **`src/app/application/`** — Use-case orchestration across `ingest`, `persistence`, `messaging`, `enrichment`, `probe`, `plate`, `splice`, `process`, `gauge`, `simulation`, and `hfgt`.
* **`src/app/infrastructure/`** — Outbound adapters for PostgreSQL (`psycopg`), NATS JetStream (`nats-py`), tensor/manifold operations, and runtime execution.
* **`src/app/interfaces/http/`** — Inbound FastAPI HTTP shell (`app.py`, `wiring.py`, `settings.py`, `security.py`, `errors.py`, `schemas.py`, `routes/`). Only `app.interfaces.http.wiring` may import from `app.infrastructure`.

Key documentation and contracts:
* [Documentation Index](docs/README.md)
* [HTTP API Architecture (`0.9.9` Shell)](docs/architecture/HTTP_API.md)
* [Generated OpenAPI Contract](docs/contracts/OPENAPI.json)
* [Security Policy](SECURITY.md) & [Data Policy](DATA_POLICY.md)

---

## Installation

Install the core package along with the optional HTTP API, PostgreSQL, and NATS JetStream extras:

```bash
python -m pip install ".[api,postgres,nats]" -r requirements-ci.txt