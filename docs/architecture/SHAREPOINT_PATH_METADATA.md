---
title: Read-only path metadata candidates and dictionary port
version: 0.1.0-proposal
status: proposed-port-review-required
tags: [currentcraft, architecture, evidence, reference, adapter]
---

# Read-only path metadata candidates and dictionary port

> [!warning]
> Design only. No application contract, adapter, loader, generated reference or
> conformance implementation is delivered by this page. Stop for coordinator
> review before encoding the proposed dictionary shape. This page does not
> approve production mappings, source access, source mutation or release policy.

## Purpose and Done-when

Interpret an already supplied document folder path as uncertain evidence for
client, project, phase-folder and document-class metadata. A folder is a prior,
not truth. Retain every input evidence item, including unknown and misfiled paths.
A future synthetic implementation is complete only when every result preserves
an opaque source locator and selected dictionary snapshot id, version and hash;
misfiled/conflicting fixtures remain low-confidence candidates; generated
contract references and boundary/conformance tests pass.

## Grounding and dependency gate

Follow [docs-first](../DOCS_FIRST.md), the
[source adapter boundary](SOURCE_ADAPTER_BOUNDARY.md), the
[reference boundary](../../references/README.md), and the read-only restriction
in [document lifecycle Decision 4](../domain/DOCUMENT_LIFECYCLE.md).
This design does not adopt that document's unresolved inheritance or lifecycle
proposals and does not modify document-domain behavior.

Existing `app.application.enterprise.contracts.ReferenceDictionary` is
`enterprise-reference-v1.1`: units, stages and process types. Its
`ReferenceSelection` distinguishes file, payload and whole-dictionary hashes.
`app.infrastructure.enterprise.references.load_references` loads that contract
from explicitly configured hash-pinned files. Neither defines folder-rule
entries or a path-metadata consumer port. Do not extend their accepted schemas,
hashes, constructors or loader to accommodate this proposal silently.

**Decision gate:** a new typed path-rule projection is needed. Its selection,
validity, canonical digest and rule semantics would constrain the future loader's
output, even without prescribing a file format. Only this design page is added.
Do not implement contracts, generated docs, adapter or tests until the coordinator
accepts or revises the consumer-port proposal. The file-based dictionary loader
belongs to a separate lane and remains out of scope.

## Proposed responsibility split

The private caller supplies folder segments and independently selected reference
context in memory. An application Protocol describes the typed consumer view;
a generic infrastructure adapter matches synthetic/in-memory data. A future
loader may produce that view directly or through an explicit mapper. No on-disk
schema, configured root, discovery mechanism, serialization format or loader API
is prescribed here. Never execute a class name or expression supplied as data.

Proposed placement after approval: application contracts/Protocol under
`app.application.path_metadata`; pure read-only matching under
`app.infrastructure.path_metadata`; synthetic conformance tests in `tests/`;
a generated contract reference registered through the existing generator.
Use the shared `_Frozen`, descriptions on every field, closed input schemas,
immutable tuples and array-free Protocols. These are planned locations, not
implemented packages or a decision to modify packaging now.

## Proposed entities and typed port (design notation, not runnable code)

- `PathDictionaryRequest`: opaque snapshot id, version, expected canonical
  SHA-256 and timezone-aware valid-at time. Trusted composition supplies the pin;
  an incoming serialized receipt is not independent verification.
- `PathDictionaryPort.get_snapshot(request: PathDictionaryRequest) ->
  PathDictionarySnapshot`: lookup of an already available in-memory consumer
  snapshot only. No path, file handle, source client or credentials are accepted.
- `PathDictionarySnapshot`: schema discriminator `currentcraft-path-reference/v1`,
  opaque snapshot id, version, canonical SHA-256, half-open valid interval,
  provenance evidence reference, and an ordered immutable tuple of typed rules.
- `PathRule`: unique opaque rule id, exact folder-segment pattern, one allowlisted
  target kind (`client`, `project`, `phase_folder`, `document_class`), opaque
  target value, and optional explicit contextual scope. No arbitrary metadata,
  Python imports, regex execution or executable expressions.
- `PathEvidence`: opaque source/document and source-version references, opaque
  private-evidence handle, already separated folder segments, and optional
  independently supplied intake-binding context. The filename is not an input
  to project identity. Raw folder segments stay inside the authorized private
  matching boundary, never in outward diagnostics or public output.
- `CandidateMetadata`: target kind, optional opaque candidate value, literal
  `candidate` status, confidence band, safe reason code, matching rule reference
  when present, source locator, and snapshot id/version/canonical hash.
- `SourceLocator`: opaque private-evidence handle plus zero-based half-open
  segment span and opaque source-version reference. Authorized private resolution
  recovers original paths; results never carry a real URL or reversible raw path.
- `PathMetadataResult`: retained input evidence reference, snapshot receipt,
  candidate tuple, and controlled diagnostic codes. It is not a document,
  identity update, lifecycle transition, authorization or readiness decision.

Every candidate repeats the snapshot receipt so it remains attributable outside
its enclosing result. Record source version and selected rule references without
claiming that a hash establishes semantic correctness or approval.

## Proposed deterministic matching and confidence rules

1. Treat paths as supplied segment tuples. Do not read files, infer source roots,
   follow links, URL-decode, case-fold or trim silently. Initial matching is
   exact, case-sensitive, contiguous segment matching; these semantics require
   review, not inference from enterprise conventions. Empty paths are retained.
2. Preserve rule order for provenance; output is deterministically sorted by
   target kind, rule id and segment span. Duplicate rule ids, unsupported target
   kinds, invalid spans/time ranges, incompatible schema versions, broken
   references and hash/pin mismatch are controlled configuration failures.
3. Proposed canonical hash: SHA-256 over UTF-8 canonical JSON of schema version,
   snapshot id, version, validity, provenance and ordered rules, excluding the
   digest field itself; sorted object keys, compact separators, no NaN values,
   explicitly normalized UTC timestamps. Keep this digest distinct from raw-file
   and existing enterprise-payload digests. Final canonicalization needs approval
   before a loader or contract relies on it.
4. An uncontradicted matching rule produces at most `medium` confidence. Folder
   evidence alone never produces `high`, `confirmed`, a project binding or an
   approval. Confidence is a policy band, not a calibrated probability.
5. Conflicting rule matches, a supplied independent-context mismatch, or a
   fixture's explicit contradictory evidence produce `low` confidence with a
   safe conflict code. Retain all alternatives; do not silently choose one or
   overwrite the trusted intake binding. Do not use evaluation labels at runtime.
6. For each target kind with no match, retain a `low` unresolved candidate with
   null value and `unmapped_path`, including a locator and snapshot receipt.
   Do not invent a dictionary value. No-match and empty paths still return a
   result; they are not exceptions, deletions or absence claims.
7. A malformed/unavailable snapshot returns a controlled configuration-failure
   outcome through the caller's evidence-preserving error boundary. Do not
   fabricate a verified receipt or discard input evidence. Exception text must
   not expose rejected paths, rules or framework validation payloads.
8. A plausible but wrongly filed path cannot always be detected from its path
   alone. Tests must include known contradictions and explicitly distinguish
   detected misfiling from undetectable semantic errors. Retrieval retains the
   original evidence independently of matching success.

## Source immutability and privacy

This adapter consumes strings/typed values already in memory. It never opens a
source file, invokes SharePoint/Graph/WebDAV, holds a file handle, locks, checks
out, writes, updates metadata or starts an editing/co-authoring session. Its
port has no such operation. Remote acquisition/copying, throttling and content
parsing belong elsewhere; no live SharePoint compatibility is claimed.

Public code and examples use only synthetic folders and opaque synthetic
identities. Real conventions, customer/project names, dictionary values,
private mapping logic, raw source locators and reversible crosswalks remain
private/server-side. A generic matcher must not reconstruct a private convention
in its examples. Public builds must work without private packages. Do not place
credentials or evaluation labels in runtime dictionaries. Type validation and
opaque identifiers are not by themselves a complete disclosure detector.

## Acceptance cases after approval (not executed)

- Contract validation rejects unknown fields, duplicate rule ids, unknown kinds,
  invalid hashes, naive times, inverted validity and broken rule references.
- A synthetic independent in-memory port supplies a pinned snapshot; mismatched
  id/version/hash and out-of-validity selection fail safely, without file reads.
- Synthetic exact matches cover all four target kinds with rule/span locators
  and snapshot id/version/hash on every candidate; repeated runs are identical.
- Unknown, empty, partial, overlapping and ambiguous paths remain represented;
  unmatched kinds have low-confidence unresolved candidates.
- Misfiled fixtures with independently supplied contradictions return low
  candidates and retain every conflicting alternative and evidence reference.
- Candidate project values never replace an explicit intake binding; filenames,
  folder names and latest timestamps never establish project identity/authority.
- A hostile fake source/file client fails on any open, lock, checkout, write or
  metadata-update operation; matching cannot call it because none is injected.
- Synthetic privacy sentinels in path segments, dictionary values, source URLs
  and exception payloads never appear in outward logs, generated examples or
  result serialization; only approved opaque references cross the boundary.
- Application/domain imports stay layered; domain performs no filesystem reads;
  declarative values cannot select executable classes. Existing persisted ids
  and all protected modules remain unchanged.
- Generate contract references and run drift, layering, public CI, release and
  governance acceptance checks; report actual pass/skip/fail counts separately
  from private semantic validation and live-service acceptance.

## Limits, non-goals and coordinator decision

No file-based loader, ingest integration, HTTP wiring, deployment changes,
OpenAPI changes, document-domain changes, source crawling, lifecycle transition,
semantic truth claims or real reference values are delivered. No merge.

Recommended decision: approve a **separate, loader-neutral path-rule consumer
projection**, rather than adding path rules to `enterprise-reference-v1.1`.
Confirm the proposed identity/hash/valid-time semantics and conservative matching
policy, or request changes before any code is written. The loader owner remains
free to choose storage/validation internals but must review the output contract.
Existing enterprise contracts and loader remain unchanged in either case until
an explicit migration is separately authorized.
