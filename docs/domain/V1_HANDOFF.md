# Developer handoff: enterprise V1 capture proposal

Patch base: `2a6dbfd64745f78a727a3af76c1157de2d869857` on main.
All 483 baseline text blobs were checked against GitHub's blob SHAs: zero
mismatches. The implementation was first delivered as a review patch against
that base. Publication and hosted CI status are recorded in the associated pull
request; the results below describe observed local validation. No deployment or
acceptance-task updates are performed by this change.

## Result and scope

Pydantic v2 is retained in the domain at James's explicit direction. Its speed
has not been benchmarked here. The implementation extends existing canonical
modules rather than adding parallel Project/Employee/product/process models.
29 concrete record types can hydrate through a statically allowlisted,
discriminated application contract. Definitions remain `v1-proposal`, not
accepted operating rules. Resource and version bases add capture behavior;
remaining historical scaffolds retain their previous two-field contracts.

The one-command synthetic fixture builds nine records, one process execution,
explicit stage mapping and evidenced capability binding. It saves entity
revisions, a snapshot and one simulated domain.stored outbox event atomically
using existing repository/UoW contracts and MemoryStore, then reloads them.
No stock is reserved, no broker message is dispatched, and no live allocations
or physical units are created. Modified entity content requires a new immutable
record revision; optimistic conflicts roll back the entire transaction.

Optional commercial, booking, shipment, BOM and contextual-role branches are
exercised separately. People/resources never become process operands.

Documents and readiness transitions fail closed because approval policies are
not supplied. A role/scope/evidence label does not become a grant, and an AI
resource cannot be supplied as a human decision executor. No positive operating
transition has been approved or tested as an approved business rule.

## Review order and changed-file map

Read V1_DOMAIN.md and IMPLEMENTATION_MAP.md first. The latter maps actual paths
to every proposed work-order concept. The patch/snippet bundle includes an exact
changed-file manifest with hashes. Its full-file snippets distinguish new files
from replacements; generated schemas/docs are reproduced through the existing
generators instead of a second generation system.

Key changes: existing canonical entity modules; shared identity/fact/unit values;
enterprise application contracts and use cases; explicit-root hash-pinned
reference loader and composition; one synthetic reference file and fixture;
domain/integration tests; existing schema/docs generators; package/release/CI
allowlists. Numerical runtime source is unchanged.

The API extra was already present on this base. No obsolete API-extra repair was
applied. Outside-checkout installation did reveal omitted existing splice
packages; those package patterns are now included. CI installs the API extra
and test dependencies, because the test suite imports HTTP modules. Pydantic
2.13.4 is pinned for CI/schema generation in requirements-ci.txt; the package's
runtime dependency range is retained. Two pre-existing generated-doc failures
under that version were corrected by running the existing generators. The
resulting Decimal schema updates are also generated output, not numerical
runtime changes.

## Apply and run in VS Code

Inspect local changes first. The patch is not intended to overwrite unrelated
work. From the repository root, use your own path to the extracted patch:

```powershell
git rev-parse HEAD
git status --short
git apply --check "C:\path\to\currentcraft-v1.patch"
git apply "C:\path\to\currentcraft-v1.patch"
python -m pip install -e ".[api]" -r requirements-ci.txt
python examples/domain_bootstrap.py
python -m unittest tests.domain.test_enterprise tests.integration.test_enterprise -v
```

For manual edits, use VSCode-Snippets.md: each section identifies an exact path
and provides that file's complete replacement or new content. Keep the full-file
patch as the authoritative change set, including generated output. Re-run the
existing generators if you change contracts.

The repository's complete gate is `bash scripts/ci_public.sh` (Git Bash/WSL on
Windows). Equivalent PowerShell commands are:

```powershell
python scripts/check_release.py
python scripts/gen_contract_docs.py --check
python scripts/gen_gauge_contract_docs.py --check
python scripts/gen_agency_contract_docs.py --check
python scripts/gen_domain_scaffold_docs.py --check
python scripts/gen_persistence_docs.py --check
python -m unittest discover -s tests -t . -v
```

If generated output is stale after changing a contract, run its same generator
without --check, review the diff, and run the checks again.

## Observed local validation

Environment: Linux x86_64, CPython 3.12.14, Pydantic 2.13.4, NumPy 2.3.5,
FastAPI 0.141.1, HTTPX 0.28.1 and Uvicorn 0.52.1.

| Check / exact command | Observed result |
| --- | --- |
| Baseline: `python -m unittest discover -s tests -t .` | 424 tests, two existing generated Markdown drift failures, 46 skips |
| New: `python -m unittest tests.domain.test_enterprise tests.integration.test_enterprise -v` | 50 tests, all passed, no skips |
| Full: `bash scripts/ci_public.sh` | 474 tests, 428 passed, zero failures/errors, 46 skips; all generated-doc, release and layering gates passed |
| `git diff --check` | passed |
| `python -m pip install --no-deps --no-build-isolation --upgrade --target /tmp/currentcraft-installed .` | wheel built and installed |
| From /tmp, with `PYTHONPATH=/tmp/currentcraft-installed`: import all 251 source module names | 251 imported, zero errors, including enterprise, HTTP and previously omitted splice packages |
| From /tmp with the installed wheel: build_fixture(explicit_reference_root), capture_snapshot, restore_snapshot | equality round-trip passed; nine canonical entities plus snapshot persisted |
| `PYTHONPATH=src python examples/domain_bootstrap.py` during development; installed fixture also checked outside checkout | deterministic output below |

```json
{
  "event_status": "simulated",
  "executions": 1,
  "outbox_events": 1,
  "purpose": "synthetic_fixture",
  "records": 9,
  "round_trip": "passed",
  "stored_version": 1,
  "transition": "transition blocked: scoped human authority is missing"
}
```

The 46 skips comprise 26 DuckDB stand-in tests (optional dependency absent),
17 PostgreSQL tests (driver/DSN absent), one NATS test (no disposable server),
and two private-data checks (private inputs not supplied). They are not claimed
as passes. No private source files were requested or copied into public output.

## HTTP, services and readiness status

The existing HTTP shell has health/readiness/auth routes; this patch adds no
enterprise HTTP endpoint. Using the installed wheel and FastAPI TestClient with
explicitly injected offline dependency callbacks produced /healthz 200,
/readyz 503 and /v1/auth/check 401 without a token. Those are shell tests,
not real database/broker integration. Default startup was also attempted through
the ASGI lifespan and failed with the observed configuration error:
`Required configuration variable DATAMESH_API_TOKEN_FILE is not set.`

After configuring the documented token files, database DSN and NATS server,
the existing startup command is:

```powershell
python -m pip install -e ".[api,postgres,nats]"
python -m uvicorn app.interfaces.http.app:create_app --factory --host 127.0.0.1 --port 8000
```

Consult docs/architecture/HTTP_API.md for the existing service setup. No real
PostgreSQL/NATS integration, hosted CI run, deployment, persistent server or
production readiness was observed or claimed here. The suite was run on Python
3.12 only; the hosted Python 3.11 matrix remains unobserved.

## Decisions still required

The governing task contents remain unavailable. The V1_DOMAIN.md ledger records
this acceptance blocker plus unresolved authority/permissions, readiness and
document lifecycle, drawing inheritance, vendor overlap, structural nesting,
custody/holding, commercial vocabulary and business dictionaries/field owners.
Review those decisions before introducing a success path for operational work.
Synthetic fixtures, local tests and analytical contracts are not process
validation or semantic acceptance. No existing review task is marked complete.
