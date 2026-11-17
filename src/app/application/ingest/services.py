"""Ingestion use cases: hierarchical subscriptions, adapter routing, ring appends, tensor batches."""

from __future__ import annotations

from datetime import datetime
from typing import Mapping, Optional

from app.application.messaging.contracts import EventEnvelope, make_event
from app.application.messaging.ports import MessageBrokerPort
from app.application.simulation.ports import TensorStorePort

from .contracts import AdapterResult, BlobRef, ConsumerSpec, IntakeBinding, IngestConfig, JsonMapping, RawItem, Rejection, TensorBatch
from .ports import BlobStorePort, SourceAdapterPort, TensorizerPort
from .ring import IngestRing, RingFull


_BINDING_KEYS = ("subject_kind", "subject_namespace", "subject_ref", "document_type", "revision_label")


def _flat_binding(b: Optional[IntakeBinding]) -> dict:
    """Envelope payloads are flat scalars: carry the intake binding as binding_* keys."""
    return {f"binding_{k}": getattr(b, k) for k in _BINDING_KEYS} if b is not None else {}


def _unflat_binding(p: dict) -> Optional[IntakeBinding]:
    if not p.get("binding_subject_ref"):
        return None
    return IntakeBinding(**{k: p.get(f"binding_{k}") for k in _BINDING_KEYS})


def raw_item_event(raw: RawItem) -> EventEnvelope:
    """Build the shared intake envelope without publishing or reading blob bytes."""
    return make_event(topic=raw.topic, kind="raw.item", source=raw.platform, epistemic_status="computed",
                         occurred_at=raw.received_at,
                         payload={"platform": raw.platform, "format": raw.format, "source_id": raw.source_id,
                                  "content_key": raw.content.key, "content_sha256": raw.content.sha256,
                                  "size": raw.content.size, "media_type": raw.content.media_type,
                                  "mapping": raw.mapping, "contract_name": raw.contract_name,
                                  **_flat_binding(raw.binding)})


class IngestPipeline:
    """Subscribes to raw topic patterns, routes each raw item to its format adapter, appends objects to the ring."""

    def __init__(self, broker: MessageBrokerPort, blobs: BlobStorePort, adapters: Mapping[str, SourceAdapterPort],
                 ring: IngestRing, config: IngestConfig, tensorizer: TensorizerPort, store: TensorStorePort,
                 mappings: tuple[JsonMapping, ...] = (), subscriptions: tuple[str, ...] = ("raw/#",)):
        self.broker, self.blobs, self.adapters, self.ring, self.config = broker, blobs, dict(adapters), ring, config
        self.tensorizer, self.store = tensorizer, store
        self.mappings = {m.name: m for m in mappings}
        self.rejections: list[Rejection] = []
        self._raw: dict[str, RawItem] = {}
        self._done: set[str] = set()
        self.deferred: list[tuple[RawItem, EventEnvelope]] = []   # backpressure: raw items waiting for ring space
        self.subscriptions = tuple(broker.subscribe(p, self._on_raw) for p in subscriptions)

    def receive(self, raw: RawItem) -> EventEnvelope:
        """Publish a raw item to its hierarchical topic. Handlers on matching subscriptions do the rest."""
        if not self.blobs.contains(raw.content.key, raw.content.sha256):
            raise ValueError("raw content is not in the blob store")
        env = raw_item_event(raw)
        self._raw[env.event_id] = raw
        n_deferred = len(self.deferred)
        if not self.broker.publish(env):
            self._raw.pop(env.event_id, None)   # identical raw event already published: idempotent no-op
        if len(self.deferred) > n_deferred and self.deferred[-1][1].event_id == env.event_id:
            raise RingFull(f"{raw.topic} deferred: ring full; commit consumers, then retry_deferred()")
        return env

    def retry_deferred(self) -> int:
        """Re-run deferred raw items in order; returns how many completed. Stops at the first that still does not fit."""
        done = 0
        while self.deferred:
            raw, env = self.deferred[0]
            if not self._process(raw, env):
                break
            self.deferred.pop(0)
            done += 1
        return done

    def _on_raw(self, env: EventEnvelope) -> None:
        if env.event_id in self._done:   # overlapping subscriptions deliver once
            return
        self._done.add(env.event_id)
        raw = self._raw.pop(env.event_id, None)
        if raw is None:  # a raw event from another producer: rebuild the item from the envelope
            p = env.payload
            raw = RawItem(platform=p["platform"], format=p["format"], source_id=p["source_id"], received_at=env.occurred_at,
                          content=BlobRef(key=p["content_key"], sha256=p["content_sha256"], size=p["size"],
                                          media_type=p["media_type"]),
                          mapping=p.get("mapping"), contract_name=p.get("contract_name"),
                          binding=_unflat_binding(p))
        if self.deferred or not self._process(raw, env):   # keep intake order behind earlier deferred items
            self.deferred.append((raw, env))

    def _process(self, raw: RawItem, env: EventEnvelope) -> bool:
        """Parse and append. False when the ring is full (appends so far stay; a retry is idempotent)."""
        adapter = self.adapters.get(raw.format)
        result = (adapter.parse(raw, self.config, self.mappings) if adapter is not None else
                  AdapterResult(rejection=Rejection(topic=raw.topic, content_sha256=raw.content.sha256, adapter="router",
                                                    reason=f"no adapter for format {raw.format}", received_at=raw.received_at)))
        if result.rejection is not None:
            r = result.rejection
            self.rejections.append(r)
            self.broker.publish(make_event(topic="quarantine/" + raw.topic.split("/", 1)[1], kind="ingest.rejection",
                                           source=r.adapter, epistemic_status="computed", occurred_at=raw.received_at,
                                           causation_id=env.event_id,
                                           payload={"reason": r.reason, "content_sha256": r.content_sha256}))
            return True
        for obj in result.objects:
            try:
                off = self.ring.append(obj)
            except RingFull:
                return False
            if off is None:
                continue
            self.broker.publish(make_event(topic=f"domain/{obj.kind}/{obj.object_id}", kind="domain.object",
                                           source=obj.provenance.adapter, epistemic_status="computed",
                                           occurred_at=raw.received_at, causation_id=env.event_id,
                                           payload={"object_id": obj.object_id, "kind": obj.kind, "offset": off,
                                                    "digest": obj.digest(), "content_sha256": raw.content.sha256}))
        return True

    def tensors(self, spec: ConsumerSpec) -> "TensorService":
        self.ring.register(spec.name, spec.kinds)
        return TensorService(self.ring, self.tensorizer, self.store, {spec.name: spec})


class TensorService:
    """Poll a consumer's batch from the ring, build its tensors, commit only after success."""

    def __init__(self, ring: IngestRing, tensorizer: TensorizerPort, store: TensorStorePort, specs: dict[str, ConsumerSpec]):
        self.ring, self.tensorizer, self.store, self.specs = ring, tensorizer, store, specs

    def next_batch(self, consumer: str) -> Optional[TensorBatch]:
        spec = self.specs[consumer]
        entries = self.ring.poll(consumer, spec.batch_size)
        if not entries:
            return None
        batch = self.tensorizer.build(consumer, spec.plan, entries)   # an exception leaves the batch uncommitted
        if batch.plan_digest != spec.plan.digest() or batch.offsets != tuple(e.offset for e in entries):
            raise ValueError("tensor batch lineage mismatch")
        self.ring.commit(consumer, entries[-1].offset)
        return batch
