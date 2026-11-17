# S3 unreferenced-object review gate (0.9.6)

**Unreferenced means candidate, never permission to delete.** Every candidate requires an explicit independent authorized human review. No automatic approval, no expiry-to-approval, no storage DELETE implementation in this release.

## Implemented

`app.application.persistence.deletion_review.DeletionReviewGate` reuses the aggregate repository's compare-and-swap and version history. Works with memory and SQL repositories; no new database migration required.

1. A trusted inventory provider inspects an exact managed object identity. Its count must include **all retaining references**, including historical revisions and shared documents, plus holds, active read/extraction leases and explicit retention clearance. Current-head graph edges alone are not sufficient.
2. Eligible inventory creates a **pending** review, including immutable content identity, inventory generation, requester, rationale and expiry (at most 24 hours).
3. A distinct authenticated principal with review authority approves or rejects with a rationale. Approval rechecks inventory freshness (five minutes), identity, generation, retaining references, holds, leases, availability and retention clearance.
4. Pending/approved/rejected records and decisions remain in persisted version history.
5. `check_review` revalidates approval, deadline, current reviewer authority and inventory. Changed object identity or generation requires a **new review**. A missing/unavailable provider fails closed.

Inventory generation must change whenever identity, references, holds, leases, policy or availability changes, even if a subsequent observation returns the same zero counts. Observed time must not be future-dated. Requester/reviewer identities come from authenticated application context, never user-submitted claims. Reviewer authority must be supplied by an actual authorization integration; the gate ships no permissive default or hard-coded production reviewer.

## Decision meaning

`approved` means **review approved on the recorded evidence**. It is not an executable token and not a completed deletion. `asserted` source hierarchy is also unrelated to storage deletion authority. Reviewer rejection never qualifies; pending and expired records never qualify. Status history may still say approved after expiration, but validation refuses it.

## Deliberately not wired to S3 deletion

The current toolkit has no S3 inventory registry, production authorization provider, garbage collector or S3 delete executor. The Compose worker does not scan for or delete unreferenced objects. These review APIs are not exposed as an unauthenticated CLI/HTTP endpoint. Fabric remains only the S3-compatible document store; no vendor notifications or workflow features are assumed, and no SQS is introduced.

Before connecting a future delete executor:

- Atomically fence new reference creation/read leases and hold changes against a claimed deletion job in the authoritative registry. A separate read-only check followed by S3 DELETE has a race and **must not** be used as authorization.
- Require the reviewed exact object/version and still-current generation; recheck policy/approval at claim time; never select by prefix or filename alone.
- Require a human-approved manifest of targets. This API reviews one object per record, not an implicit bucket/prefix-wide approval.
- Scope deletion credentials to the managed prefix, separate from intake/extraction credentials.
- Handle idempotent retries and verify actual physical deletion, including object versions if applicable. Persist outcomes and publish completion from an outbox. A broker publish acknowledgment is not proof of deletion.
- Protect mandatory purge decisions, legal holds, backups and derived content under their own explicit policy/authority. No durations are invented here. Unknown retention clearance blocks candidacy.

## Tests

`python -m unittest tests.test_deletion_review -v` checks memory and DuckDB-backed state/history: pending by default, independent authority, rejection, duplicate decisions, reference/hold/lease blocks, unavailable inventory, changed snapshot/identity, revoked authority, expiry and stale/future inventory. DuckDB tests are not PostgreSQL compatibility proof; no S3 operation executes.
