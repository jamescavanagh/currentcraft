# V1 review corrections: contract before implementation

Starting remote SHA: `391013bb195f0906da7dbb3dc05714d1d9dd2b36`.
Its complete source tree is `f5eab9a9f9f44d1a915bb801fa7aa759b97a3c65`;
the local baseline tree was checked to match exactly, including executable mode.
Source: James's supplied review-corrections handoff. Private source text and URLs
are not copied into the public repository. D04/D05/D08 below are the confirmed
requirements restated in that handoff, not inferred from historical diagrams.

## Confirmed direction and superseded requirement

Pydantic is approved in domain. This explicitly supersedes the earlier work
order's framework-free/Pydantic prohibition. Existing Pydantic domain models
stay. Domain validation remains deterministic and free of file/network reads,
persistence, broker dispatch, HTTP and numerical runtime dependencies. Reuse
the existing process, incidence, capability and authority contracts.

## Definitions and proposed encodings

All new field names/encodings below are implementation proposals. They are not
approval, renewal, exclusivity, delegation, inference-correctness or operating
policy. They retain opaque identity, evidence IDs and explicit null-with-reason.

| Requirement | Contract / identity / field authority | Invariants and missingness |
| --- | --- | --- |
| D08 ManufacturerRep | Existing relationship identity; representative and manufacturer Party IDs; territory Fact; agreement DateBounds; contacts Fact of Party IDs; optional project Fact | Source owns assertions. Known dates must be ordered; either bound can be unknown. Contacts resolve to existing parties. Project is optional, not a universal requirement. No vendor/labor/approval classification is inferred. |
| D04 Stakeholder | Existing relationship with party, role Fact and exactly one typed ProjectContext or SubsystemContext | Project endpoints resolve to Project. Subsystem context checks both typed IDs and project membership. Contract and decision variants remain blocked: canonical Contract/GateDecision are undefined scaffolds. |
| D05 Consultant | Existing engagement with Party and typed context/role; explicit approval-claim IDs | Party may have evidenced individual/firm form; this does not infer qualifications or authority. Context dependencies match D04. |
| ConsultantApprovalClaim | Application-owned claim ID, engagement ID, typed context, existing AuthorityRef, explicit executor Fact and missing authority-evidence reason | Claim is always unverified. Referenced executor/evidence must resolve when supplied. Missing evidence/executor can be captured explicitly but prevents execution. Scope is the existing AuthorityRef vocabulary. Delegation, grant context/validity/revocation and readiness policy remain undefined. |
| Fact epistemic status | Required observed/inferred/unknown label on each fact | Unknown value requires unknown status and nonblank reason. Known value requires observed/inferred status, evidence and no missing reason. No silent legacy status inference. |
| QualityEvidence / Derivation | Existing evidence identity and source/version/locator/time/status; optional explicit method reference and input-evidence IDs for inferred assertions | Inferred assertion must name a derivation. Observed inputs may support an inferred conclusion. Unknown evidence alone cannot support a known claim. |
| ReferenceSelection | Application contract recording full-byte hash, canonical payload hash, dictionary identity/version/full-model digest, selection time and method | Only an independently supplied selection from trusted composition/verified loading is accepted for capture. A receipt/hash inside an incoming payload is not independent verification. |

The epistemic support rule is a proposed representation/validation discipline:
an observed fact needs observed source assertion support; an inferred fact needs
an explicit inferred conclusion whose acyclic derivation reaches observed input.
Unknown inputs may be retained as uncertainty but cannot be the only support.
This is not a claim that an algorithm, observation or conclusion is correct.
The derivation method is an evidenced locator/version, never executable code.

## Trust and historical restore

Hydration validates shape and cross-record consistency, not source-file bytes.
Capture additionally requires a separate ReferenceSelection supplied by the
trusted composition root after the loader checks a configured expected hash.
It compares the full-file hash, dictionary identity/version, semantic and full
model digests and selection time/window. This is an application trust boundary,
not a cryptographic defense against malicious code running inside that root.

Capture records the selection receipt atomically with the snapshot. Historical
restore validates recorded consistency without reopening the original file or
claiming fresh byte verification. The repository is trusted to preserve the
recorded receipt; no digital signature or external attestation is invented.
Re-capture still needs an independent selection even when a receipt is present.

## Schema / validation matrix

| Guarantee | JSON Schema | Pydantic | Application | Operational policy |
| --- | --- | --- | --- | --- |
| Typed fields / closed alternatives | yes | yes | allowlist | no grant |
| Fact null/reason/status/evidence presence | conditional rules | validator | resolves and checks epistemic support | no truth/correctness approval |
| ShipmentLine exact variant | oneOf over Fact.value | validator | resolves referenced objects | custody remains blocked |
| Evidence hash/reason pairing | conditional rules including defaults | validator | source status/time/support | no authority |
| Quantity wire form | canonical nonnegative finite decimal string | JSON accepts strings only; Python also accepts Decimal/int | selected unit dictionary | no conversion/spend authority |
| Date/time ordering | formats only; no cross-property comparison | known bounds compared | future evidence/window checks | scheduling policy undefined |
| Cross-record identity/context/derivation | not expressible locally | local parts only | yes | no grant |
| Full-byte reference verification | no | hash shape only | independent trusted selection required | no grant |
| Human authority/readiness | no | claim shape only | rejects missing/mistyped evidence/executor | undefined, deny release |

The wire entry point is hydrate_snapshot_json (or model_validate_json); do not
decode a wire payload and rely on the Python convenience entry point to enforce
JSON token rules. Format assertions require a validator configured to check
formats; the parity suite uses Draft202012Validator with FormatChecker.

JSON Quantity numbers, including integer tokens and 1.0, are rejected. Python
integer/Decimal convenience input is supported before canonical JSON output as
decimal strings. Fractional float, bool, non-finite and negative values are
rejected through both paths. Canonical string syntax, including exponent and
signed-zero representation, is a proposed encoding, not a unit/business policy.

## Versioning and migration

These changes use enterprise-v1.1 payloads and a new synthetic reference version.
Fact statuses and typed relationship contexts are explicit schema changes.
Legacy v1 payloads are not silently labeled observed or freshly verified. They
require an explicit source-backed migration; no production data migration is
performed. The old synthetic file remains as historical material. Current
v1.1 captures can restore with the original file unavailable.

## Remaining decision gaps

Contract/decision context endpoints, real grant identity/context/validity and
revocation/delegation, readiness/document lifecycle, drawing inheritance,
vendor overlap and custody/holding remain blocked or undefined. Broader private
semantic source access remains unavailable. None is replaced by old diagrams.

Fresh verification evidence, requirement-to-test links, full-schema inspection,
dependency versions and per-environment statuses will be recorded after the
implementation is tested. Previous 474/50 counts are historical, not new results.

## Requirement-to-test map

| Requirement | Executable evidence |
| --- | --- |
| D08 attributes, missingness, ordered known bounds, typed contacts, capture/restore | tests.integration.test_review_corrections.ReviewCorrections.test_d08_* |
| D04 supported alternatives, typed endpoints, project membership, blocked undefined branches | same module: test_d04_* |
| D05 individual/firm claims, scope/context, evidence/executor missingness, no permission grant | same module: test_d05_*; original tests.integration.test_enterprise tests for AI and role-only authority remain |
| Observation vs inference, observed inputs, unknown-only support, cycles and unknown references | same module: test_known_*, test_inference_*, test_unknown_inputs_*, test_derivation_* |
| Existing future-evidence invariant | same module: test_existing_future_evidence_guard_remains_active; original guard preserved |
| Full-byte verification | original tests.integration.test_enterprise.ReferenceLoading.test_wrong_full_file_hash_is_rejected retained; new forged-payload and independent-selection tests exercise capture |
| Payload tampering / closed reference fields | original ReferenceLoading.test_unsupported_dictionary_fields_and_types_are_rejected retained |
| Version/window/metadata selection and historical restore | new test_wrong_selection_*, test_dictionary_metadata_*, test_loader_rejects_*, test_historical_* |
| Fact / ShipmentLine / QualityEvidence / Quantity schema and JSON entry behavior | tests.domain.test_schema_parity.SchemaParity.test_fact_*, test_shipment_*, test_source_hash_*, test_inferred_evidence_*, test_quantity_* |
| Model/application limits vs local schema | same class: test_date_ordering_*, test_cross_record_resolution_*; no policy enforcement is claimed by schema |
| Complete snapshot artifact and internal references | same class: test_entire_generated_snapshot_schema_is_read_and_matches_model; existing generator --check retained |
| Approved Pydantic and deterministic domain boundary | tests.test_domain_scaffold.DomainScaffold.test_confirmed_pydantic_direction_and_deterministic_construction plus existing layering tests |

The suspected generator regex issue was not changed: the actual generator source
executes successfully and its full generated output passes the drift checks.
