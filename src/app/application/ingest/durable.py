"""Durable ingestion handler: adapters feed repositories, not the ephemeral tensor ring.

The generic TransactionalWorker wraps this handler with inbox deduplication and commit-before-ack.
"""
from __future__ import annotations

from typing import Literal, Mapping

from app.application.messaging.contracts import EventEnvelope, make_event
from app.application.persistence.ports import UnitOfWork
from .contracts import BlobRef, IngestConfig, JsonMapping, RawItem, AdapterResult, Rejection
from .ports import BlobStorePort, SourceAdapterPort
from .services import _unflat_binding


class DurableIngestHandler:
    def __init__(self, blobs: BlobStorePort, adapters: Mapping[str, SourceAdapterPort], config: IngestConfig,
                 mappings: tuple[JsonMapping, ...] = ()):
        self.blobs, self.adapters, self.config = blobs, dict(adapters), config
        self.mappings = {m.name: m for m in mappings}

    def __call__(self, uow: UnitOfWork, event: EventEnvelope) -> Literal["applied", "rejected"]:
        if event.kind != "raw.item":
            raise ValueError("durable ingest accepts raw.item only")
        p = event.payload
        raw = RawItem(platform=p["platform"], format=p["format"], source_id=p["source_id"], received_at=event.occurred_at,
                      content=BlobRef(key=p["content_key"], sha256=p["content_sha256"], size=p["size"], media_type=p["media_type"]),
                      mapping=p.get("mapping"), contract_name=p.get("contract_name"), binding=_unflat_binding(p))
        if event.topic != raw.topic:
            raise ValueError("intake topic and payload disagree")
        if not self.blobs.contains(raw.content.key, raw.content.sha256):
            raise FileNotFoundError("blob unavailable or digest mismatch")
        adapter = self.adapters.get(raw.format)
        result = adapter.parse(raw, self.config, self.mappings) if adapter else AdapterResult(
            rejection=Rejection(topic=raw.topic, content_sha256=raw.content.sha256, adapter="router",
                                reason="no adapter for source format", received_at=raw.received_at))
        if result.rejection:
            r = result.rejection
            uow.outbox.add(make_event(topic="quarantine/" + raw.topic.split("/", 1)[1], kind="ingest.rejection",
                                      source=r.adapter, epistemic_status="computed", occurred_at=raw.received_at,
                                      causation_id=event.event_id,
                                      payload={"reason": r.reason, "content_sha256": r.content_sha256}), raw.received_at)
            return "rejected"
        for obj in result.objects:
            stored = uow.objects.put(obj)
            if stored.stored:
                uow.outbox.add(make_event(topic=f"stored/{obj.kind}/{obj.object_id}", kind="domain.stored",
                                          source="persistence", epistemic_status="computed", occurred_at=raw.received_at,
                                          causation_id=event.event_id,
                                          payload={"object_id": obj.object_id, "kind": obj.kind,
                                                   "version_no": stored.version_no, "digest": obj.digest()}), raw.received_at)
        return "applied"
