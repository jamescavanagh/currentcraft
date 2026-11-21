# Intake slice changelog (0.10.0 work in progress)

## Implemented

Authenticated POST /v1/intake/documents for text/XLSX, streaming 64 MiB file limit, bounded multipart input and cleanup, explicit complete IntakeBinding, threadpool blob writes, private durable first-receipt selection, confirmed JetStream publishing, opaque receipt/status handles, and GET /v1/intake/{event_id} over the shared worker inbox marker. Queued is not extracted; processed source occurrences are not approved work. Retries are not restore commands.

Typed intake container dependencies reuse the merged read endpoints' uow_factory and preserve their HandleCodec. Wiring remains the only HTTP infrastructure composition root. Existing configuration names, secret-file handling and persisted object identities are unchanged. API_PREREQUISITES is now indexed. OpenAPI was regenerated with scripts/gen_openapi.py after integrating merged PR #25. Synthetic intake, receipt and wiring tests cover the boundaries and failure paths.

## Acceptance evidence

Governing toolkit 0.1.1 archive checksum verified; installed wheel; dmgov accept exited 0 with zero layering/path findings and five passing controls. Fresh-export acceptance also passed. The obsolete four-path exception is dropped. Focused combined local suite: 131 passed, no skips. Local full public gate: generated checks passed, then 706 discovered cases included 685 passes, 20 gated skips and one import error due to absent jsonschema. Hosted CI is reported separately in the PR, not inferred from local results.

## Not claimed

No local PostgreSQL, NATS, Docker, combined live HTTP intake acceptance, multi-host receipt-storage guarantee, private enterprise-term certification, production readiness, merge, deployment or release version bump. The existing root CHANGELOG and merged Compose entries are retained unchanged; this additive slice record avoids overwriting their history.
