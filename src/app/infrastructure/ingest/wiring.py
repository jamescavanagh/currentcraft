"""Build an ingestion pipeline on the shared tensor store and a broker."""

from __future__ import annotations

import json
from datetime import datetime

from app.application.ingest.contracts import IngestConfig, RawItem
from app.application.ingest.ring import IngestRing
from app.application.ingest.services import IngestPipeline
from app.infrastructure.messaging.memory import InMemoryBroker
from app.infrastructure.tensors.numpy_store import InMemoryNumpyTensorStore

from .adapters import default_adapters
from .blobs import InMemoryBlobStore
from .tensorizer import NumpyTensorizer

MEDIA = {"email": "message/rfc822", "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
         "pdf": "application/pdf", "json": "application/json", "data_contract": "application/json", "text": "text/plain",
         "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"}


def build_ingest(config: IngestConfig, mappings=(), contracts=None, capacity=10000, store=None, broker=None,
                 subscriptions=("raw/#",), profiles=()) -> IngestPipeline:
    store = InMemoryNumpyTensorStore() if store is None else store
    broker = InMemoryBroker() if broker is None else broker
    blobs = InMemoryBlobStore()
    pipe = IngestPipeline(broker=broker, blobs=blobs, adapters=default_adapters(blobs, contracts, {p.name: p for p in profiles}), ring=IngestRing(capacity),
                          config=config, tensorizer=NumpyTensorizer(store), store=store, mappings=tuple(mappings),
                          subscriptions=tuple(subscriptions))
    return pipe


def put_raw(pipe: IngestPipeline, *, platform: str, fmt: str, source_id: str, received_at: datetime, data: bytes | None = None,
            json_body=None, mapping=None, contract_name=None, media_type=None, binding=None) -> RawItem:
    """Store content in the pipeline's blob store and return its RawItem (infrastructure helper)."""
    if (data is None) == (json_body is None):
        raise ValueError("give exactly one of data or json_body")
    if json_body is not None:
        data = json.dumps(json_body, sort_keys=True).encode()
    ref = pipe.blobs.put(data, media_type or MEDIA[fmt])
    return RawItem(platform=platform, format=fmt, source_id=source_id, received_at=received_at, content=ref,
                   mapping=mapping, contract_name=contract_name, binding=binding)


def build_durable_ingest(*, broker, uow_factory, blobs, config, spec, profiles=(), mappings=(), contracts=None,
                         handler_id="ingest-v1", max_attempts=5, retry_delay=5.0):
    """Compose durable intake -> source adapters -> repositories + outbox -> commit -> broker ack.

    Caller awaits broker.ensure_consumer(spec), then worker.run_batch(). Shared blob access is explicit.
    The synchronous IngestPipeline/IngestRing remain independent local/simulation APIs.
    """
    from app.application.ingest.durable import DurableIngestHandler
    from app.application.messaging.durable import TransactionalWorker
    handler = DurableIngestHandler(blobs, default_adapters(blobs, contracts, {p.name: p for p in profiles}), config,
                                   tuple(mappings))
    return TransactionalWorker(broker, uow_factory, spec, handler_id, handler, max_attempts, retry_delay)
