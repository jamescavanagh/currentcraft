---
title: Synthetic models and evidence
status: contract-only alpha
tags: [currentcraft, models, synthetic]
---

# Synthetic models and evidence

Design source for `app.application.models`, schema `currentcraft-models/v1`.
This slice adds three immutable contracts and pure checks over supplied exact records.
No storage, resolvers, extraction, sanitization, training, permissions, approval,
deployment or operational source access. All instances are synthetic only.
Existing persisted identities, phase contracts and label history are unchanged.

## ConfigurationArtifactRevision

An exact capture has separate artifact/revision identity, exact-byte digest, opaque
payload reference, explicit product-instance binding and versioned applicability
profile. Source version is unknown only with a controlled reason. Capture is not
application, device readback, approval or proof of applicability.

## DatasetManifest

Pin ordered input revisions/digests, mapping/build configuration, method, split
policy/assignments, feature/label specifications, run and creation time. Input and
digest tuples align; each input has exactly one split assignment in input order.
Group/case-level separation and absence of label leakage require independent checks
against resolved records. Distinct specification references do not prove independence.

## SanitizationAssessment

Pin exact input and optional output, tool/rules/mapping/configuration, method,
coverage profile, required/inspected/unresolved surfaces, findings and execution.
Processed requires output and complete declared coverage; it never means safe or
approved. Blocked has no usable output. Review-required may reference a restricted
candidate. Nonprocessed outcomes require controlled limitation codes.
Coverage consistency is not proof of inspection. A trusted resolved profile must
establish required surfaces. Findings references contain no values or source excerpts.

## Exact association to phase/v1

`check_phase_assessment` accepts resolved PhaseReading, SanitizationAssessment and
PhaseRevision instances. It checks exact phase, assessment source identity/revision,
and mapping/configuration digests. The reading method and run describe reading
production and may differ from the assessment operation. Observation and assessment
times remain distinct. No validity promotion occurs. Phase decisions/events still
cite reading ids, never artifact or assessment ids.

`check_dataset_artifacts` and `check_assessment_artifacts` validate supplied artifact
references and digests, rejecting duplicate supplied refs. They cannot authenticate
records, inspect bytes, authorize access, or validate applicability/coverage profiles.
Callers must load canonical exact versions through trusted resolvers later.

## Invariants

- Frozen closed Pydantic contracts; descriptions on every field; no arrays.
- Reuse phase identifier/revision/digest conventions without modifying phase/v1.
- Aware times require non-null UTC offsets. Unknown dates are not reconstructed.
- Canonical fingerprint: SHA-256 of UTF-8 JSON for all declared fields, sorted keys,
  compact separators, ASCII escaping, no NaN; tuple order is significant.
- Fingerprints establish declared-record integrity, not content truth or semantic equivalence.
- Handles and limitation codes are syntax-checked, not secret-scanned or registry-verified.
- Human LabelEvent and AcceptanceDecision remain separate existing contracts.
- No new identity derivation, release/version bump, API or production policy.

## Implemented / not claimed

Implemented: three contracts, pure association checks, fingerprints, synthetic
negative/positive tests, generated reference/schemas, packaging/release registration.
Generator drift is checked in the synthetic unittest discovery path.
Not implemented: ports/adapters, source rights, sanitizer, dataset builder, group
split checks, leak detection, decisions, persistence, encoders or model training.
Local targeted, full-checkout and hosted CI evidence are reported separately in the PR.

See [generated reference](../contracts/MODELS_EVIDENCE_CONTRACTS.md).
