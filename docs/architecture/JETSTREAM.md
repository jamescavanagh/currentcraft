---
title: Durable broker adapter (NATS JetStream)
version: 0.9.3
status: implemented; live-server test gated, not executed in the sandbox
tags: [datamesh, architecture, messaging, ingestion]
---

# Durable broker adapter: NATS JetStream

## Decision and boundary

NATS + JetStream is the durable central event transport. PostgreSQL remains authoritative for committed objects, versions, inbox processing and reservations. Blob storage holds source bytes. A stream sequence is **not** a business version, and broker delivery is **not** gate approval or resource authorization.

The old `MessageBrokerPort` / `InMemoryBroker` remain synchronous local/simulation APIs. Network adapters implement the **separate async** `DurableBrokerPort`, never pretend to execute callbacks inline, and never return unbounded history tuples. MQTT edge bridging and RabbitMQ are not implemented by this release.

| Layer | Implementation |
| --- | --- |
| Application contracts/ports | `messaging.durable`: `PublishReceipt`, `DurableConsumerSpec`, `DurableDelivery`, `DurableBrokerPort` |
| Application use cases | `TransactionalWorker`, `relay_durable_outbox`; `ingest.durable.DurableIngestHandler`; `ingest.services.raw_item_event` |
| Infrastructure adapters | `messaging.jetstream.JetStreamBroker`, lazy `connect_jetstream`; `messaging.subjects`; deterministic `InMemoryDurableBroker` test double |
| Composition | `infrastructure.ingest.wiring.build_durable_ingest` takes broker, UoW factory, shared blob store, profiles and config explicitly |
| Local shared-volume blobs | `infrastructure.ingest.directory_blobs.DirectoryBlobStore`: content-addressed filenames, digest verification, 64 MiB default limit, atomic replace; not a permission service or production object store |

## The implemented path

```text
source file -> durable/shared blob -> raw_item_event -> JetStream DM_RAW
    -> durable pull worker -> declared format adapter -> validated source objects
    -> one PostgreSQL transaction: object versions + edges + inbox marker + outbox
    -> commit -> source-delivery ack_sync

outbox relay -> confirmed JetStream publish -> mark that event published in PostgreSQL
    -> independent event consumers (embedding/graph/UI implementations are future work)
```

The durable intake path does not write into `IngestRing`: that ring is process-local, not a recovery mechanism. Downstream workers must read committed objects by reference/version and construct their tensor batches independently. The existing local pipeline keeps its ring behavior unchanged.

## Streams and policies

Administrative `broker.provision()` creates these streams or verifies that existing policies match. It refuses mismatches rather than silently modifying retention or replication.

| Stream | Topic families | Default per-stream policy |
| --- | --- | --- |
| `DM_RAW` | `raw` | file storage, Limits retention, DiscardNew |
| `DM_EVENTS` | `stored`, `domain`, `gate`, `object`, `hil`, `plate` | same |
| `DM_TELEMETRY` | `iot`, `telemetry` | same, separate capacity pool |
| `DM_QUARANTINE` | `quarantine` | same |

Initial development defaults: **256 MiB and 7 days per stream**, 64 KiB per envelope, 120-second deduplication window, 1 replica. Configurable at provisioning; production should select 3 replicas on independent failure domains and measured capacity/age budgets. Limits still expire events even if a consumer has not processed them. DiscardNew refuses new writes at capacity, so the publisher must retain/retry its source checkpoint or outbox row. Monitor age of the oldest unprocessed event as well as storage use.

No document bytes, tensors, credentials or embedding arrays travel in messages. Subject names and headers are not secret storage either.

## Topic mapping

Slash-style application topics remain unchanged. Each literal level becomes `t` + UTF-8 hex; `.` joins encoded levels under prefix `dm`. This prevents source IDs containing dots from changing the routing hierarchy and is reversible. A literal application `+` filter maps to NATS `*`. Final `#` maps to **two** filter subjects: the exact parent and its descendants, because NATS `>` does not match the parent itself. No blind slash-to-dot replacement.

Example: `raw/file` -> `dm.t726177.t66696c65`.

Provisioned subject families are explicit; publishing an unknown family is refused. Adding a family is an administrator-reviewed stream migration, not an application-side auto-create.

## Consumer and delivery behavior

- Named durable pull consumers: same durable shares work, different durables independently fan out.
- Defaults: batch 16, shared pending-ack cap 64, ack wait 60 seconds. Incoming batches are processed sequentially; all fetched items receive lease-progress heartbeats while waiting/processing. Scale worker instances sharing the durable for parallelism; no global business ordering is promised.
- Existing consumer filters, delivery-start policy and key reliability settings must match; replay starts apply to **new** durable consumers. Use a new durable and a deliberate handler generation for rebuilding a projection.
- Publish sends `Nats-Msg-Id = event_id` and returns only after JetStream's storage acknowledgment. Publish errors propagate.
- Consumer completion uses `ack_sync`. An ack lost after commit causes redelivery, not lost work: the persistent inbox marker skips the handler on the replay.
- Inbox identity is SHA256(handler identity + validated event id); do not rename handler identities casually. Independent projection generations intentionally use distinct identities.
- Retries roll back all database work. Worker default retry delay is 5 seconds; 5 failed attempts create a **transactional quarantine event** and rejected inbox marker before acknowledging the source delivery. Error strings are not copied into quarantine; only exception class/category and source message reference. A missing shared blob is retried and eventually quarantined too.
- Server `max_deliver=-1` is intentional: it must not silently exhaust the retry budget before the worker can commit quarantine. Malformed wire messages are represented as invalid deliveries with a payload digest, not decoded private text, and follow the same quarantine-before-ack route.
- No atomic transaction spans PostgreSQL and NATS. Outbox relay can publish more than once if marking it sent fails. JetStream deduplication is windowed; persistent inbox markers are the durable protection. **No end-to-end exactly-once claim.**
- Handlers may write through the UoW only. External effects belong behind a separate command/outbox consumer; network side effects inside a handler cannot be rolled back.

## Run locally (development only)

Install from the repository root:

```bash
python3 -m venv .venv
.venv/bin/pip install '.[postgres,nats]'
# Dedicated development server only. Keep its data volume; do not expose it publicly.
docker volume create datamesh-nats
docker run -d --name datamesh-nats -p 127.0.0.1:4222:4222 \
  -v datamesh-nats:/data nats:2.11-alpine -js -sd /data
.venv/bin/python scripts/jetstream_service.py provision
```

PostgreSQL setup: [Ubuntu service](UBUNTU_POSTGRES.md). Apply the 0.9.2 migrations as an administrator first; the worker opens PostgreSQL with `run_migrations=False`.

Supply `DATAMESH_PG_DSN` and `DATAMESH_PSEUDONYM_SALT` securely to the worker process (not in CLI arguments or the repository). A source connector and its worker must see the same protected blob volume.

```bash
.venv/bin/python scripts/jetstream_service.py publish --blob-dir /srv/datamesh/blobs \
  --file ./example.txt --source-id example-document --format text
.venv/bin/python scripts/jetstream_service.py ingest --blob-dir /srv/datamesh/blobs --once
```

For PEW files: publisher adds `--format xlsx --mapping <profile-name> --binding <private-binding.json>`; worker adds `--profile <private-profile.json>`. Binding is an `IntakeBinding` JSON object naming an actual project or opportunity. The private profile is already shipped under `references/private/`; never infer the project's identity from the workbook. The generic CLI has no built-in JSON mapping or domain contract registry; compose those through `build_durable_ingest` in Python.

`--server` is repeatable; `--credentials` supplies a protected NATS credentials file; `--ca-file` supplies TLS trust. Provision with separate administrator credentials. Runtime worker accounts need only their subjects, consumer operations, reply inboxes and JetStream API permissions. This release does not generate production account/JWT/ACL policy, install a broker systemd service, or deploy source connectors.

## Tests and acceptance

```bash
python -m unittest tests.test_durable_messaging -v
# Dedicated disposable server ONLY: integration test provisions and deletes DM_* streams.
DATAMESH_NATS_URL=nats://127.0.0.1:4222 python -m unittest tests.test_durable_messaging.JetStreamIntegration -v
```

Local tests cover codec collisions, wildcard semantics, consumer independence, delayed retry, expiry, commit-before-ack, ack-loss replay, rollback/quarantine, outbox publish failure, PEW adapter persistence and blob integrity. Real-server integration tests storage confirmation, deduplication, redelivery, durable progress across **client** reconnect and replay from a sequence. Broker-node restart, cluster failover, TLS/ACLs, production load and PostgreSQL+NATS combined fault injection remain unproven. The GitHub `jetstream` job starts a disposable NATS 2.11 server; it has not run in this sandbox.

References: https://docs.nats.io/concepts/jetstream ; https://nats-io.github.io/nats.py/modules.html
