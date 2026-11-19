# V1.1 correction handoff

Starting remote SHA: `391013bb195f0906da7dbb3dc05714d1d9dd2b36`. The entire starting source tree was
verified as `f5eab9a9f9f44d1a915bb801fa7aa759b97a3c65`, including file mode.
This is the correction to the merged first V1 capture slice. The associated
review PR supplies the final commit SHA; the machine-readable
[V1_REVIEW_VERIFICATION.json](V1_REVIEW_VERIFICATION.json) pins the verified source
and generated artifacts by SHA-256. That inventory excludes this narrative and
itself to avoid self-referential hashes.

## Result and review order

Pydantic stays in domain, explicitly superseding the obsolete prohibition.
Read [V1_DOMAIN.md](V1_DOMAIN.md), [V1_REVIEW_CORRECTIONS.md](V1_REVIEW_CORRECTIONS.md)
and [IMPLEMENTATION_MAP.md](IMPLEMENTATION_MAP.md) first. They separate confirmed
D04/D05/D08 meanings from proposed encodings and still-blocked policy.

ManufacturerRep now captures territory, independently unknown/known agreement
bounds, typed contact parties and optional project scope. Stakeholder and
Consultant use exactly one typed project/subsystem context. Consultant approval
claims explicitly link the existing AuthorityRef, scope, evidence and executor;
claims are always unverified and never grant authority. Party form can capture
individual or firm without inventing qualification/delegation rules.

Fact status is explicit. Known observations require observed source assertion
support. Inferred conclusions have a separate evidence assertion and derivation
that may consume observed inputs; unknown-only support is insufficient. This
support discipline is a proposed encoding, not an approved inference algorithm
or truth policy. The existing future-evidence check is retained and tested.

Capture now requires an independent loader-issued ReferenceSelection; a hash or
receipt inside incoming data is not proof of verification. Capture compares the
full-file hash, semantic hash, full dictionary/model hash, identity, version and
as-of/window. Restore validates recorded provenance without re-reading the
original file or claiming fresh verification. Re-capture still needs independent
selection. The trust assumption is trusted composition/repository, not defense
against hostile code inside the same process or forged database history.

Local JSON Schema conditions now cover Fact, ShipmentLine and evidence pairing.
Quantity's JSON wire form is an exact finite nonnegative decimal string; Python
additionally accepts Decimal/int convenience input. JSON numbers, floats, bools,
negative and non-finite values are rejected as documented. The validation matrix
states which checks require Pydantic, application references or operating policy.

## Schema and API migration

Payload contracts advance to enterprise-v1.1; package release metadata remains
0.9.9. Fact statuses and typed contexts are required schema changes. Import paths
remain canonical. Legacy v1 data must be mapped from source, with real evidence;
it is not automatically relabeled observed or freshly verified. No production
data migration is performed. The old synthetic reference file is retained, and
the fixture uses the new pinned v1.1 reference asset.

Use build_fixture_with_selection for capture, or pass the independent selection
from load_references to capture_snapshot. build_fixture remains a structural
fixture helper. Wire payloads use hydrate_snapshot_json; Python hydration is a
separate convenience entry point. Operational release still has no success path.

## Fresh observed verification

All commands below were executed for this correction. Counts from the earlier
handoff are not reused as fresh evidence.

Environment: Linux x86_64; CPython 3.12.14; Pydantic 2.13.4,
NumPy 2.3.5, jsonschema 4.26.0, FastAPI 0.141.1, HTTPX 0.28.1,
Uvicorn 0.52.1, setuptools 84.2.1.

| Command / check | Exit | Observed result |
| --- | --- | --- |
| Starting tree: bash scripts/ci_public.sh | 0 | 474 tests, 428 passed, 46 skipped; fresh baseline execution |
| Correction: bash scripts/ci_public.sh | 0 | 509 tests, 463 passed, 46 skipped, no failures/errors; release, layering and drift gates passed |
| python -m unittest tests.domain.test_enterprise tests.domain.test_schema_parity tests.integration.test_enterprise tests.integration.test_review_corrections -v | 0 | 84 tests passed, no skips |
| New parity/review modules alone | 0 | 34 tests passed; one additional approved-boundary test is included in the full suite |
| python scripts/gen_agency_contract_docs.py | 0 | 159 generated files; generator source otherwise preserved |
| python scripts/gen_agency_contract_docs.py --check | 0 | full current generated output matches |
| git diff --check | 0 | clean |
| python -m pip wheel --no-deps --no-build-isolation --wheel-dir /tmp/currentcraft-review-wheel-final . | 0 | wheel built |
| python -m pip install --no-deps --upgrade --target /tmp/currentcraft-review-installed-final /tmp/currentcraft-review-wheel-final/datamesh_agency_toolkit-0.9.9-py3-none-any.whl | 0 | wheel installed |
| From /tmp/currentcraft-review-runtime, PYTHONPATH=/tmp/currentcraft-review-installed-final: import every source module name | 0 | 252 of 252 imported; app resolved from installed target |
| Same outside-checkout environment: examples/domain_bootstrap.py with separately copied current public reference asset | 0 | nine records, one execution, atomic capture/restore and blocked release |

The 46 skips are 26 optional DuckDB stand-in checks, 17 PostgreSQL checks lacking
a local configured driver/DSN, one NATS check lacking a disposable local server,
and two private-input checks. They are not reported as passes. A development
run caught a default executor Fact remaining an unvalidated dict; enabling
validated defaults on the claim model fixed it. Final runs have no errors.

Wheel SHA-256: `9ca0e9fc067bc6cfdc99b4f708a51d25e07202a3cecdd4b2e612e173c9fefa01`.

The installed fixture uses an independently copied
references/public/enterprise.synthetic.v1.1.json under the temporary runtime root.
Reference assets are explicit configuration, not assumed to exist in the wheel
or read by domain models. The existing manifest includes the new source asset.
No check depends on importing app from the source checkout working directory.

## Full schema inspection

The complete local EnterpriseSnapshot schema was read and parsed: 118185 bytes,
58 definitions. It matches model_json_schema, passes
Draft202012Validator.check_schema, and every internal $ref resolves. It validates
the current synthetic wire fixture. The parity suite also demonstrates a dangling
record reference passing structural schema/model validation but failing the
application boundary, and known date-order reversal requiring model validation.
No page-text extraction or truncated schema retrieval is used as evidence.

Schema SHA-256: `0771e9e8c1cdb3c18d5390677bd211f8502364206e9966d3a288bdc85f7c417c`.

## Fixture result

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

## Runtime status kept separate

- Local tests, deterministic fixture, in-memory persistence, package build,
  outside-checkout imports and copied-reference fixture: passed as above.
- HTTP shell with injected offline dependencies: /healthz 200, /readyz 503,
  /v1/auth/check 401 without token. ASGI lifespan was exercised through TestClient.
- Default HTTP startup: blocked with observed error
  `Required configuration variable DATAMESH_API_TOKEN_FILE is not set.`
- Local real PostgreSQL/NATS integration: unverified; prerequisites absent.
- Hosted CI for starting merge 391013b: observed successful run 44224942631.
  Correction-head hosted status belongs to the associated PR and is separate
  from this local proof. Python 3.11 was not run locally.
- Deployment or persistent hosted service: not attempted. No enterprise HTTP
  endpoint, production allocation or positive authorization is introduced.

## Reproduce in VS Code

From the corrected repository root, using your selected Python environment:

```powershell
python -m pip install -e ".[api]" -r requirements-ci.txt
python examples/domain_bootstrap.py
python -m unittest tests.domain.test_enterprise tests.domain.test_schema_parity tests.integration.test_enterprise tests.integration.test_review_corrections -v
python scripts/check_release.py
python scripts/gen_contract_docs.py --check
python scripts/gen_gauge_contract_docs.py --check
python scripts/gen_agency_contract_docs.py --check
python scripts/gen_domain_scaffold_docs.py --check
python scripts/gen_persistence_docs.py --check
python -m unittest discover -s tests -t . -v
```

Git Bash/WSL can run the equivalent full gate: bash scripts/ci_public.sh. To run
the existing HTTP shell, first configure its token files, database and broker as
specified in docs/architecture/HTTP_API.md, install the additional postgres/nats
extras, then use the existing Uvicorn factory command. It was not established as
a persistent running service by this work.

## Remaining gaps

D04 contract/decision branches are explicitly blocked because canonical Contract
and GateDecision remain undefined scaffolds. D05 captures claims but cannot
verify a real grant: holder identity, delegation, validity/revocation and readiness
policy remain undefined. Drawing inheritance, vendor overlap, custody and broader
private semantic sources remain open. The requirement-to-test map is in
V1_REVIEW_CORRECTIONS.md. No review/acceptance task is marked complete.
