"""Provision streams, publish a file intake reference, or run the durable ingestion worker.

No credentials belong in arguments: use NATS credentials files and DATAMESH_PG_DSN / DATAMESH_PSEUDONYM_SALT.
"""
import argparse
import asyncio
import json
import os
import signal
import ssl
from datetime import datetime, timezone
from pathlib import Path

from app.application.ingest import IngestConfig, IntakeBinding, RawItem, WorkbookProfile
from app.application.ingest.services import raw_item_event
from app.application.messaging.durable import DurableConsumerSpec, relay_durable_outbox
from app.infrastructure.ingest.directory_blobs import DirectoryBlobStore
from app.infrastructure.ingest.wiring import MEDIA, build_durable_ingest
from app.infrastructure.messaging import connect_jetstream
from app.infrastructure.persistence import build_postgres


def arguments():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('mode', choices=('provision', 'publish', 'ingest'))
    p.add_argument('--server', action='append', help='repeat for seed servers; no embedded secrets; default localhost')
    p.add_argument('--credentials', help='protected NATS credentials file (different admin/worker credentials in production)')
    p.add_argument('--ca-file', help='CA bundle for TLS server verification')
    p.add_argument('--replicas', type=int, choices=(1, 3), default=1)
    p.add_argument('--blob-dir', help='protected shared blob volume, required for publish/ingest')
    p.add_argument('--profile', action='append', default=[], help='local workbook profile JSON, repeatable')
    p.add_argument('--durable', default='ingest-v1')
    p.add_argument('--once', action='store_true', help='process one batch and relay pending outbox')
    p.add_argument('--file', help='source file (publish only)')
    p.add_argument('--format', choices=tuple(MEDIA), default='text')
    p.add_argument('--source-id', help='stable source document id, not revision id')
    p.add_argument('--mapping', help='declared workbook profile name (JSON mappings require custom composition)')
    p.add_argument('--binding', help='private IntakeBinding JSON file; project/opportunity is never guessed')
    return p.parse_args()


async def run(args):
    if args.mode != 'provision' and not args.blob_dir:
        raise ValueError('--blob-dir required')
    if args.mode == 'publish' and (not args.file or not args.source_id):
        raise ValueError('--file and --source-id required')
    broker = await connect_jetstream(tuple(args.server or ['nats://127.0.0.1:4222']), credentials=args.credentials,
                                     tls=ssl.create_default_context(cafile=args.ca_file) if args.ca_file else None)
    try:
        if args.mode == 'provision':
            await broker.provision(replicas=args.replicas)
            print('Stream policies verified. One replica is development only; configure auth/TLS and HA separately.')
            return
        blobs = DirectoryBlobStore(args.blob_dir)
        if args.mode == 'publish':
            path = Path(args.file)
            if path.stat().st_size > blobs.max_bytes:
                raise ValueError('file exceeds blob limit')
            raw = RawItem(platform='file', format=args.format, source_id=args.source_id,
                          received_at=datetime.now(timezone.utc), content=blobs.put(path.read_bytes(), MEDIA[args.format]),
                          mapping=args.mapping,
                          binding=IntakeBinding.model_validate(json.loads(Path(args.binding).read_text())) if args.binding else None)
            receipt = await broker.publish(raw_item_event(raw))
            print(f'Confirmed intake: {receipt.stream} sequence {receipt.sequence} (not a business version).')
            return
        # Migrations are an administrator step. Workers do not provision streams or database schema.
        uow = build_postgres(os.environ['DATAMESH_PG_DSN'], run_migrations=False)
        config = IngestConfig(pseudonym_salt=os.environ['DATAMESH_PSEUDONYM_SALT'])
        profiles = tuple(WorkbookProfile.model_validate(json.loads(Path(p).read_text())) for p in args.profile)
        spec = DurableConsumerSpec(stream='DM_RAW', durable=args.durable, pattern='raw/#')
        await broker.ensure_consumer(spec)
        worker = build_durable_ingest(broker=broker, uow_factory=uow, blobs=blobs, config=config, spec=spec, profiles=profiles)
        stop = asyncio.Event()
        loop = asyncio.get_running_loop()
        for sig in (signal.SIGINT, signal.SIGTERM):
            loop.add_signal_handler(sig, stop.set)
        while not stop.is_set():
            await worker.run_batch(timeout=1.0)
            await relay_durable_outbox(uow, broker, datetime.now(timezone.utc))
            if args.once:
                break
    finally:
        await broker.close()


if __name__ == '__main__':
    asyncio.run(run(arguments()))
