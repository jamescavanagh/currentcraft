# Local NATS + PostgreSQL Compose stack (0.9.4)

**Single-host development/integration stack**, not production HA. Requirements: Docker Engine with Compose **v2.20+**, Python 3.11+, internet for image pulls and the Python image build. Run from the extracted repository root. No Python dependencies are needed on the host for the lifecycle helper.

## Start and test

```bash
python3 scripts/local_stack.py config   # generate local secrets + validate Compose
python3 scripts/local_stack.py up       # build image, initialize DB/streams, start worker
python3 scripts/local_stack.py smoke    # verify an end-to-end synthetic text intake
python3 scripts/local_stack.py status
python3 scripts/local_stack.py logs
python3 scripts/local_stack.py down     # stops/removes containers and network; retains volumes and secrets
```

The file is `deploy/local/compose.json`. JSON is valid Compose YAML syntax; use it explicitly via `docker compose -f deploy/local/compose.json ...`. The helper supplies that argument for you.

## Services

| Service | Function |
| --- | --- |
| postgres | PostgreSQL 18, SCRAM host auth; admin password supplied by file, restricted app login created on first database initialization |
| nats | NATS 2.11 JetStream, generated token authentication, file-backed storage |
| prepare | one-shot root process sets ownership of shared blob/NATS volumes, no credentials |
| bootstrap | nonroot one-shot migrations + verified stream policies; exits successfully before worker starts |
| worker | nonroot UID 10001; durable adapter ingestion and confirmed outbox relay; retries restart on service failure |
| smoke (tools profile) | publishes unique synthetic text, waits for its committed Postgres object and confirmed stored event; temporary event consumer removed afterwards |
| publisher (tools profile) | submits an explicitly selected local file reference, no database credential access |

Postgres: `127.0.0.1:5433`. NATS: `127.0.0.1:4222`. Override host ports before invoking the helper via `DATAMESH_PG_PORT` and `DATAMESH_NATS_PORT`. Containers use internal DNS `postgres:5432`, `nats:4222`. No monitoring or cluster ports are published.

Named volumes: `postgres_data`, `nats_data`, `blob_data` (Compose project prefix `datamesh-local`). PostgreSQL 18 mounts **/var/lib/postgresql**, matching the image's versioned data layout. NATS stores under /data. Application blob files are owned by UID 10001. The prepare container alone runs as root to set ownership on blob/NATS volume roots; NATS, bootstrap, workers and tools run as UID 10001. Postgres uses its image-provided entrypoint and database OS account.

Bootstrap waits on PostgreSQL readiness and retries the authenticated NATS connection. Worker startup requires successful bootstrap. Failures are visible via `status` and `logs`; no failure is silently treated as readiness. A database readiness probe is not an application compatibility proof; use the smoke test.

## Secrets and persistence

`local/compose-secrets/` is generated at first use, Git-ignored, excluded from exports and images. It contains independent admin/app passwords, NATS token/config and stable pseudonym salt. Existing secrets are retained and validated on every run. **Do not regenerate them while reusing volumes**: the PostgreSQL init script only runs on a fresh volume, and a changed salt changes pseudonymous resource identities.

File-backed Compose secrets keep host ownership/mode. For nonroot container reads the individual files are 0444, protected on the host by an enclosing 0700 directory. Docker administrators/root can read them. This is local-development secret handling, not encryption or a production secret manager. Environment variables carry port choices and input settings only, not passwords.

The app login is not superuser and has no CREATEDB, CREATEROLE, replication or RLS-bypass privilege. It owns its database so bootstrap can apply migrations. Production should separate migration ownership from narrower runtime privileges. The NATS token is shared local-account authentication, **not** per-subject isolation; TLS/JWT/account ACLs remain a production task. Plaintext connections stay inside the local Docker network/loopback, but are not encrypted.

The image explicitly copies only source/package files and the runtime entrypoint. Private references remain in the coordinator bundle, never image layers. The worker mounts `references/private/` read-only for explicitly selected profiles; it does not ingest that directory automatically. No secrets ship in the ZIP.

## Publish your own file

Put the input under `local/intake/` (created by the helper, excluded from Git and exports). Files mounted for the nonroot publisher must be readable by UID 10001; use an appropriate ACL/readable copy in this deliberately selected directory.

```bash
# Copy a test document to local/intake/example.txt first.
DATAMESH_INPUT_FILE=example.txt DATAMESH_SOURCE_ID=example-document \
  docker compose -f deploy/local/compose.json --profile tools run --rm publisher
```

For PEW, substitute your actual bundled profile filename and its internal name below, then publish with an actual intake binding (the example names are placeholders):

```bash
DATAMESH_WORKBOOK_PROFILES=/references/private/estimate-profile.json \
  python3 scripts/local_stack.py up
# DATAMESH_MAPPING must match the selected profile's name exactly.
DATAMESH_INPUT_FILE=estimate.xlsx DATAMESH_INPUT_FORMAT=xlsx \
DATAMESH_SOURCE_ID=estimate-document DATAMESH_MAPPING=estimate-profile \
DATAMESH_BINDING_FILE=binding.json \
  docker compose -f deploy/local/compose.json --profile tools run --rm publisher
```

`binding.json` lives under local/intake/ and follows `IntakeBinding`: subject_kind, subject_namespace, subject_ref, document_type, optional revision_label. Supply the real project/opportunity; do not use an example reference as a real identity. A workbook does not identify its own project. Publish confirmation means durable intake, not successful extraction; inspect the repository/quarantine for processing outcome. Without the private profile, unknown workbook mappings are rejected rather than guessed. Arbitrary JSON mappings and custom domain registries require Python composition rather than this generic publisher.

## Operations and limits

- `down` never deletes volumes. No destructive reset command is provided. Restore database, broker and blob data coherently with the original secret set.
- Never run the standalone JetStreamIntegration test against this retained stack: that test deletes DM_* streams. Use disposable CI infrastructure.
- One replica, bounded 7-day/256-MiB-per-stream policies inherited from 0.9.3. Expiry is real: this is not an indefinite evidence archive. Postgres remains state authority, blobs remain source authority, JetStream is transport/replay inside retention bounds.
- Images pin major/minor release lines, **not immutable digests**; record resolved image digests and exact driver/server versions after validation. No pgvector extension is included in the stock postgres image.
- No backups, external connector checkpoint services, metrics dashboard, HA/failover or production TLS/ACL deployment is supplied.

## Acceptance status

### Real HTTP upload-and-poll smoke

`smoke` and `api-smoke` first retain the existing shell/auth probes, then submit
one fresh synthetic text document over authenticated multipart HTTP to
`POST /v1/intake/documents`. A random source ID on every invocation prevents
old inbox markers from satisfying a new run. Require a 202 durable-queue
receipt with the expected digest, DM_RAW stream and strictly validated opaque
receipt/source handles. Only the exact relative intake status path derived
from that opaque receipt may be polled; never follow a server-supplied origin.

Poll authenticated HTTP status until the real worker has committed `processed`.
Pending is not failure or proof of queue membership; quarantined, malformed
JSON/receipt/status, unexpected HTTP status and transport errors fail closed.
The upload, polling and final identical-upload retry share one 60-second
monotonic deadline, four-second maximum per request and bounded response bodies.
Host proxies and redirects are disabled. Never print tokens, source IDs,
receipt handles, body contents, response error details or raw exceptions.

Repeat the same upload within that deadline and require the same opaque event,
source and status handles, digest and stream sequence, with broker duplicate
confirmation; status remains processed. This is retry behavior within the broker
deduplication window, not exactly-once or restoration. Queued means not extracted;
processed means committed source occurrences, never approved work.

The existing compose-smoke workflow already invokes `local_stack.py smoke`
before and after restarting PostgreSQL, NATS and worker. Both invocations must
now run this HTTP smoke against the real stack, with a fresh source each time.
No workflow-file edits, weakened checks, private profiles or host HTTP packages
are required. Static/mocked helper tests are not live execution evidence.
API-process restart, fault injection, full read-route live acceptance and a
production-readiness or release claim remain outside this smoke.

Static Compose structure, first-run/rerun secret handling, nonroot/image boundaries, shell syntax and Python compilation are tested locally. The `compose-smoke` CI job builds/starts the actual stack, runs the integration smoke and repeats after container restarts. **It has not run in the sandbox, which has no Docker daemon or internet access.** Shipping a runnable stack definition is not an executed deployment claim.
