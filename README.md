# DataMesh Agency Toolkit 0.9.9

A curated, GitHub-ready **source candidate**, not the enterprise application repository. The intent is dashboards that help people understand complex systems-integration projects, see feasible alternatives and exercise meaningful agency. Numerical vortex/geodesic measurements are exploratory instruments, not validated project facts, authorizations or operational forecasts.

## Scope

Implementation layer since 0.5.0 (design sources in `docs/`, open the folder in Obsidian; start at `docs/README.md`):

- Process-first domain contracts: process executions, object lifecycles, gates that release only with authority, evidence and computed status.
- Plate + spatial isosceles three-body simulation: 2D plate with global spin and local vortices, object body crossing the plate, analytic arc bounds for certified velocity winding.
- Embedding enrichment chamber: sparse condensation code and shortcut candidates against height-preserving and axis-shuffle nulls (0.6.0).
- Probe backend: aperture, spin gauges, Barrier Lyapunov search brackets, lens terms, candidate clusters and human label events (0.7.0).
- Ingestion: hierarchical raw topics, email/docx/pdf/json/data-contract/text adapters, pseudonymous resources, quarantine, IngestRing with backpressure, tensor plans with lineage (0.8.0). `pip install datamesh-agency-toolkit[pdf]` for PDF text.
- Project estimation workbooks (0.9.1): `xlsx` intake through a declared `WorkbookProfile`; the workbook becomes a project document tied to its project or opportunity by an `IntakeBinding`, and tasks are extracted as a WBS with an explicit hierarchy column, task x role demand, BOM lines and part-number claims, plus diagnostics. Source occurrences only; promotion into `app.domain` is a reviewed step.
- Durable broker (0.9.3): async NATS JetStream adapter, confirmed publishing, durable pull consumers, reversible topic mapping, transactional inbox/outbox workers and repository-backed PEW ingestion. `pip install datamesh-agency-toolkit[nats]`. [Architecture and commands](docs/architecture/JETSTREAM.md). Live-server integration tests require `DATAMESH_NATS_URL`; not executed in the sandbox.
- Persistence (0.9.2): repository ports and a unit of work in `app.application.persistence`; PostgreSQL 18 SQL repositories, migrations, optional pgvector columns and an in-memory adapter in `app.infrastructure.persistence`. Source occurrences with versioned typed edges, compare-and-swap aggregates, idempotent commands, non-overcommitting stock reservations, embeddings and a transactional outbox. `pip install datamesh-agency-toolkit[postgres]`. PostgreSQL compatibility is claimed only by the `postgres-18` CI job; the DuckDB stand-in is not evidence of it.
- Domain entity scaffold: 94 unreviewed Pydantic placeholders under `app.domain`, two fields each, fail-closed (0.9.0). Namespace only; no business semantics.
- Event broker port with an in-memory adapter and plate-to-plate candidate handoff routing. MQTT/IoT adapter planned.

Carried from 0.4.0:

- Existing application/simulation TensorSpec, TensorRef, TensorContract, NodeRole and array-free ports.
- NumPy procedural field with analytic velocity Jacobian, shared tensor store and simulation adapters.
- Embedding-derived gauge connections/invariants, graph-geodesic probes and local embedding perturbations.
- Velocity-contour winding: invalid, sampled_only or certified conditional on correct supplied whole-arc bounds. Independent of leakage and gradient-energy validity.
- Synthetic tests, generated schemas, docs and CI. No enterprise fixtures, source documents, ERP adapters, internal navigation links or Git history.

The combined circular kinematic/leakage runtime, a learned embedding-to-flow bridge, continuous metric/geodesic reconstruction, automatic winding bounds and empirical process validation are NOT completed by this release. No full Phillips-Stone reconstruction or semantic benefit is claimed.

## Install and verify

Python 3.11+; locally checked on Python 3.12.

```sh
python -m pip install .
bash scripts/ci_public.sh
```

NumPy stays in infrastructure. Application interfaces carry tensor references, not arrays.

```python
from app.infrastructure.gauge import build_numpy_gauge, build_numpy_geodesic_probe
from app.application.gauge import VelocityWindingRequest
from app.infrastructure.gauge import NumpyVelocityWindingAdapter
service, store = build_numpy_gauge()
probe, _ = build_numpy_geodesic_probe(store)
```

Read docs/pipelines/GAUGE_PIPELINE.md, GEODESIC_PROBE.md and VELOCITY_WINDING.md. Existing app.* namespace retained for compatibility: do not install beside an unrelated package also owning app.*. Integrate into an existing DataMesh checkout deliberately, not by overwriting its business modules.

## Protect enterprise data

Use references/private/ locally for enterprise references and fitted mappings; never commit it. Only references/README.md and the empty public manifest template are included. The directory itself does not protect anything: exclusions, repository permissions, history checks and manual review are all necessary. Read DATA_POLICY.md and SECURITY.md.

```sh
python scripts/check_release.py
python scripts/export_public.py --out ../datamesh-public.zip
```

These are public-source allowlist tools, not a guarantee that arbitrary code or text is non-confidential. Do not add real examples without a classification review.

## Before GitHub publication

1. Confirm you have rights to publish the retained source and approve a license (see LICENSE_DECISION.md).
2. Review the complete release file list, scanner report, source diff and synthetic examples.
3. Start from this sanitized candidate in a new repository or review any existing Git history separately. No existing repository history is included or sanitized here.
4. Run the public CI and inspect the exported ZIP. Enable repository secret scanning/push protection where available.
5. Upload only after that review. This export has not published to GitHub or PyPI.

## Ubuntu PostgreSQL setup

Run `bash scripts/deploy_postgres_ubuntu.sh --dry-run`, then `sudo bash scripts/deploy_postgres_ubuntu.sh` on an Ubuntu systemd host. [Service setup, credentials and migrations](docs/architecture/UBUNTU_POSTGRES.md). Optional `--pgvector`; localhost-only dedicated cluster on port 5433. Host installation not executed in this release.

## Local integrated stack

`python3 scripts/local_stack.py smoke` builds/starts NATS + PostgreSQL + the durable ingestion worker and exercises the complete flow. Generated local secrets, persistent named volumes and localhost-only ports. [Setup, file/PEW publishing and operational limits](docs/architecture/LOCAL_COMPOSE.md). Requires Docker Compose v2.20+; no deployment executed in the sandbox.

## Deletion review gate

Version 0.9.6 adds a persisted, fail-closed review gate for unreferenced managed objects. Independent authorized review, exact identity/generation checks, expiry, holds and lease/reference checks. [Contract and integration limits](docs/architecture/DELETION_REVIEW.md). No S3 deletion or automatic garbage collection is implemented.

## Sparse phase splice

Version 0.9.9 adds the HFGT capability graph (`datamesh-hfgt/v1`): process records read as hetero-functional graph theory, with capability nodes and feasible-sequence edges for the GNN, readiness as a structural reading, and golden fixtures from a standalone reference oracle. It also makes simulation digests independent of node order and moves the shared contract base to `app.application.common`. [Design](docs/pipelines/HFGT_CAPABILITY_GRAPH.md) · [Roadmap](docs/ROADMAP.md).

Version 0.9.8 renames the Jacobian eigenvalue to mu (`mu_min_abs`) so lambda means inflow only, and moves the simulation schema to `datamesh-sim/v2`; v1 payloads still read. See [CHANGELOG](CHANGELOG.md).

Version 0.9.7 splices workbook source occurrences into a phase-blocked sparse embedding space. Phase parameters (anchors, kappa, floor, shared weight) are declared and versioned; cross-phase junctions are candidates for human labeling. [Design and phase parameters](docs/pipelines/SPARSE_PHASE_SPLICE.md).
