"""Local integration stack composition. No production credentials, topology or permissions implied."""
import asyncio
import os
import signal
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

from app.application.ingest import IngestConfig, IntakeBinding, RawItem, WorkbookProfile
from app.application.ingest.services import raw_item_event
from app.application.messaging.durable import DurableConsumerSpec, relay_durable_outbox
from app.infrastructure.ingest.directory_blobs import DirectoryBlobStore
from app.infrastructure.ingest.wiring import build_durable_ingest
from app.infrastructure.messaging.jetstream import JetStreamBroker
from app.infrastructure.persistence import build_postgres


def secret(name):
    value = (Path('/run/secrets') / name).read_text().strip()
    if len(value) != 64 or any(c not in '0123456789abcdef' for c in value):
        raise ValueError('invalid local secret: ' + name)
    return value


def database(migrate=False):
    # Generated hex passwords are URI safe. No credential URI is printed or passed in argv.
    return build_postgres('postgresql://datamesh_app:' + secret('pg_app') + '@postgres:5432/datamesh',
                          run_migrations=migrate)


async def broker():
    import nats
    # Bound retry window includes initial server startup, not just reconnect after a first connection.
    for attempt in range(60):
        try:
            nc = await nats.connect('nats://nats:4222', token=secret('nats_token'), connect_timeout=2,
                                    max_reconnect_attempts=2)
            return JetStreamBroker(nc, nc.jetstream())
        except (OSError, nats.errors.Error):
            if attempt == 59:
                raise RuntimeError('local broker not ready; inspect container logs') from None
            await asyncio.sleep(1)


async def main(mode):
    if mode == 'prepare':
        for name in ('blobs', 'nats'):
            path = Path('/srv/datamesh') / name
            path.mkdir(parents=True, exist_ok=True)
            os.chown(path, 10001, 10001)
            os.chmod(path, 0o700)
        print('Local data volumes prepared.')
        return
    if mode == 'bootstrap':
        database(migrate=True)
        b = await broker()
        try:
            await b.provision()
        finally:
            await b.close()
        print('Database migrations and durable streams ready.')
        return
    blobs = DirectoryBlobStore('/srv/datamesh/blobs')
    b = await broker()
    try:
        if mode == 'publish':
            from app.infrastructure.ingest.wiring import MEDIA
            path = Path('/intake') / os.environ['DATAMESH_INPUT_FILE']
            path = path.resolve()
            if not path.is_relative_to(Path('/intake')) or not path.is_file():
                raise ValueError('input must be a file under /intake')
            if path.stat().st_size > blobs.max_bytes:
                raise ValueError('input exceeds blob limit')
            fmt = os.environ.get('DATAMESH_INPUT_FORMAT', 'text')
            binding_name = os.environ.get('DATAMESH_BINDING_FILE')
            binding = None
            if binding_name:
                binding_path = (Path('/intake') / binding_name).resolve()
                if not binding_path.is_relative_to(Path('/intake')):
                    raise ValueError('binding must be under /intake')
                binding = IntakeBinding.model_validate_json(binding_path.read_text())
            raw = RawItem(platform='file', format=fmt, source_id=os.environ['DATAMESH_SOURCE_ID'],
                          received_at=datetime.now(timezone.utc), content=blobs.put(path.read_bytes(), MEDIA[fmt]),
                          mapping=os.environ.get('DATAMESH_MAPPING') or None, binding=binding)
            await b.publish(raw_item_event(raw))
            print('Intake durably confirmed. Processing completes independently in the worker.')
            return
        uow = database()
        if mode == 'smoke':
            source_id = 'compose-smoke-' + uuid.uuid4().hex
            raw = RawItem(platform='file', format='text', source_id=source_id, received_at=datetime.now(timezone.utc),
                          content=blobs.put(source_id.encode(), 'text/plain'))
            receipt = await b.publish(raw_item_event(raw))
            deadline = time.monotonic() + 60
            while time.monotonic() < deadline:
                with uow() as tx:
                    found = [o for o in tx.objects.by_kind('text', limit=10000) if o.provenance.source_id == source_id]
                    if found:
                        oid = found[0].object_id
                if found:
                    # Require both committed object and a confirmed committed-event publication.
                    consumer = DurableConsumerSpec(stream='DM_EVENTS', durable='smoke-' + uuid.uuid4().hex[:12],
                                                   pattern='stored/#', batch_size=32, max_ack_pending=64)
                    await b.ensure_consumer(consumer)
                    try:
                        while time.monotonic() < deadline:
                            for delivery in await b.fetch(consumer.durable, 32, 1):
                                matched = delivery.event and delivery.event.payload.get('object_id') == oid
                                await b.ack(delivery)
                                if matched:
                                    print('PASS: confirmed intake -> worker -> PostgreSQL object -> confirmed stored event.')
                                    return
                    finally:
                        await b.js.delete_consumer('DM_EVENTS', consumer.durable)
                    break
                await asyncio.sleep(0.5)
            raise RuntimeError('smoke timed out; inspect worker/bootstrap logs')
        if mode != 'worker':
            raise ValueError('unknown mode')
        profiles = []
        # Explicitly opt into private profile JSONs; never guess a document identity or ingest all private files.
        for name in os.environ.get('DATAMESH_WORKBOOK_PROFILES', '').split(','):
            if name.strip():
                profiles.append(WorkbookProfile.model_validate_json(Path(name.strip()).read_text()))
        spec = DurableConsumerSpec(stream='DM_RAW', durable='ingest-v1', pattern='raw/#')
        await b.ensure_consumer(spec)
        worker = build_durable_ingest(broker=b, uow_factory=uow, blobs=blobs,
                                      config=IngestConfig(pseudonym_salt=secret('pseudonym_salt')), spec=spec,
                                      profiles=tuple(profiles))
        stop = asyncio.Event()
        for sig in (signal.SIGINT, signal.SIGTERM):
            asyncio.get_running_loop().add_signal_handler(sig, stop.set)
        print('Durable ingestion worker ready.')
        while not stop.is_set():
            await worker.run_batch(timeout=1)
            await relay_durable_outbox(uow, b, datetime.now(timezone.utc))
    finally:
        await b.close()


if __name__ == '__main__':
    asyncio.run(main(sys.argv[1]))
