# Currentcraft

**Currentcraft is an open-source agency platform for complex systems-integration projects.** It helps people working on changing, interdependent projects understand where things stand, see what is actually possible, and know who can release the next piece of work, so they can act on evidence.

It exposes situation, alternatives, readiness and decision rights. It does not decide for people: readiness is never a release, candidates are never approved work, and simulated work can never release.

> **Status: alpha (`0.9.9`).** Contracts, persistence, messaging and an HTTP shell are implemented and tested on synthetic data. No business or process validation is claimed. Mathematical models in this repository are exploratory lenses, not validated process facts.

Currentcraft was previously developed as DataMesh; older changelog entries and design pages keep that name.

---

## What it does

- **Process-first records.** Processes act on objects (things, never people); resources execute processes through capability bindings. Gates are control executions with `hold`, `release`, `reject` or `return` decisions.
- **Evidence-bound release.** A release needs authority with release scope, verification evidence the gate actually read or checked, and computed (not simulated) status.
- **Readiness that blocks honestly.** Missing, stale or conflicting evidence blocks a transition instead of passing it.
- **Human in the loop.** Candidate relations stay candidates until a human label confirms them.
- **Ingestion with provenance.** Documents and workbooks become versioned source occurrences with lineage back to raw content.

## Architecture

A hexagonal layout with dependency boundaries enforced by AST layering tests:

- **`src/app/domain/`**: domain entities, versioning contracts and invariants. Pydantic v2 is approved here; no I/O, drivers or numerical runtimes.
- **`src/app/application/`**: use cases and contracts (`ingest`, `persistence`, `messaging`, `enrichment`, `probe`, `plate`, `splice`, `process`, `gauge`, `simulation`, `hfgt`, `enterprise`, `p4`).
- **`src/app/infrastructure/`**: adapters for PostgreSQL 18 (`psycopg`), NATS JetStream (`nats-py`), tensor operations and runtime execution.
- **`src/app/interfaces/http/`**: the FastAPI HTTP shell. Only `wiring.py` may import from `app.infrastructure`.

Persistence is append-only and versioned; events flow through durable JetStream streams with an outbox.

## Installation

Python 3.11 or later. Install the core package with the optional HTTP API, PostgreSQL and NATS extras:

```bash
python -m pip install ".[api,postgres,nats]" -r requirements-ci.txt
```

Other extras: `pdf` (PDF ingestion via pypdf).

## Run the checks

```bash
bash scripts/ci_public.sh
```

This runs the release check, verifies every generated contract (including the OpenAPI contract) is current, and runs the test suite. PostgreSQL, JetStream and Compose integration run as separate CI jobs.

## Run locally

- **Local stack** (PostgreSQL 18, NATS JetStream, worker): see [Local Compose stack](docs/architecture/LOCAL_COMPOSE.md).
- **HTTP API shell** (`/healthz`, `/readyz`, `/v1/auth/check`): see [HTTP API](docs/architecture/HTTP_API.md) for configuration and a localhost-only launch.

## Documentation

- [Documentation index](docs/README.md)
- [Docs-first design](docs/DOCS_FIRST.md): every change starts as a design page; generated contracts are CI-gated.
- [Roadmap](docs/ROADMAP.md)
- [Domain boundary](docs/architecture/DOMAIN_BOUNDARY.md)
- [Enterprise V1.1 review corrections](docs/domain/V1_REVIEW_CORRECTIONS.md)
- [HTTP API](docs/architecture/HTTP_API.md) and the [generated OpenAPI contract](docs/contracts/OPENAPI.json)
- [Changelog](CHANGELOG.md)

## Data, security and license

- [Data policy](DATA_POLICY.md): public releases are allowlisted; enterprise records and derived representations stay out of public artifacts.
- [Security](SECURITY.md)
- License: [Mozilla Public License 2.0](LICENSE.txt)
