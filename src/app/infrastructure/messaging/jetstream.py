"""NATS JetStream adapter. Optional nats-py driver; no network activity on import.

Separate async durable port: never emulates synchronous inline handlers or unbounded replay tuples.
File-backed, Limits retention, DiscardNew, explicit acks, confirmed publishes, bounded pull consumers.
"""
from __future__ import annotations

import hashlib
import uuid

from app.application.messaging.contracts import EventEnvelope
from app.application.messaging.durable import DurableConsumerSpec, DurableDelivery, PublishReceipt
from .subjects import pattern_to_subjects, subject_to_topic, topic_to_subject

# Envelope families deliberately separated by retention/volume. Prefixes are encoded, not user-supplied subjects.
STREAM_FAMILIES = {
    "DM_RAW": ("raw",),
    "DM_EVENTS": ("stored", "domain", "gate", "object", "hil", "plate"),
    "DM_TELEMETRY": ("iot", "telemetry"),
    "DM_QUARANTINE": ("quarantine",),
}


class JetStreamBroker:
    def __init__(self, connection, context):
        self.connection, self.js = connection, context
        self._subscriptions, self._specs, self._pending = {}, {}, {}

    async def provision(self, replicas: int = 1, max_bytes: int = 256 * 1024 * 1024,
                        max_age: float = 7 * 86400, duplicate_window: float = 120.0):
        """Explicit administrative operation, never automatic on connect. Existing mismatched streams are refused.
        Single replica is development only; production should use 3 replicas on separate failure domains.
        """
        from nats.js.api import StreamConfig, StorageType, RetentionPolicy, DiscardPolicy
        from nats.js.errors import NotFoundError
        if replicas not in (1, 3) or max_bytes < 1024 or max_age <= 0 or not 0 < duplicate_window <= max_age:
            raise ValueError("invalid stream storage policy")
        for name, families in STREAM_FAMILIES.items():
            subjects = [s for f in families for s in pattern_to_subjects(f + "/#")]
            config = StreamConfig(name=name, subjects=subjects, storage=StorageType.FILE,
                                  retention=RetentionPolicy.LIMITS, discard=DiscardPolicy.NEW,
                                  num_replicas=replicas, max_bytes=max_bytes, max_age=max_age,
                                  max_msg_size=65536, duplicate_window=duplicate_window)
            try:
                info = await self.js.stream_info(name)
            except NotFoundError:
                await self.js.add_stream(config=config)
                continue
            current = info.config
            for field in ("storage", "retention", "discard", "num_replicas", "max_bytes", "max_age", "max_msg_size", "duplicate_window"):
                if getattr(current, field) != getattr(config, field):
                    raise ValueError(f"stream {name}: incompatible {field}; review an explicit migration")
            if set(current.subjects) != set(subjects):
                raise ValueError(f"stream {name}: incompatible subjects")

    async def publish(self, event: EventEnvelope) -> PublishReceipt:
        event = EventEnvelope.model_validate(event.model_dump())
        family = event.topic.split("/", 1)[0]
        stream = next((s for s, fs in STREAM_FAMILIES.items() if family in fs), None)
        if stream is None:
            raise ValueError("topic family has no provisioned stream")
        payload = event.model_dump_json().encode()
        if len(payload) > 65536:
            raise ValueError("event exceeds 64 KiB; use a blob reference")
        receipt = await self.js.publish(topic_to_subject(event.topic), payload, stream=stream,
                                        headers={"Nats-Msg-Id": event.event_id})
        return PublishReceipt(stream=receipt.stream, sequence=receipt.seq, duplicate=bool(receipt.duplicate))

    async def ensure_consumer(self, spec: DurableConsumerSpec):
        from nats.js.api import ConsumerConfig, AckPolicy, DeliverPolicy, ReplayPolicy
        from nats.js.errors import NotFoundError
        if spec.stream not in STREAM_FAMILIES:
            raise ValueError("unknown stream")
        if spec.durable in self._specs:
            if self._specs[spec.durable] != spec:
                raise ValueError("durable already bound with different configuration")
            return
        if spec.pattern.split("/", 1)[0] not in STREAM_FAMILIES[spec.stream]:
            raise ValueError("filter family does not belong to stream")
        filters = list(pattern_to_subjects(spec.pattern))
        config = ConsumerConfig(durable_name=spec.durable, ack_policy=AckPolicy.EXPLICIT,
                                deliver_policy=DeliverPolicy.BY_START_SEQUENCE if spec.start_sequence else DeliverPolicy.ALL,
                                opt_start_seq=spec.start_sequence, replay_policy=ReplayPolicy.INSTANT,
                                filter_subjects=filters, ack_wait=spec.ack_wait,
                                max_ack_pending=spec.max_ack_pending, max_deliver=-1)
        # Unlimited server redelivery is intentional: the worker commits quarantine before terminal ack.
        try:
            info = await self.js.consumer_info(spec.stream, spec.durable)
        except NotFoundError:
            info = await self.js.add_consumer(spec.stream, config=config)
        for field in ("ack_policy", "ack_wait", "max_ack_pending", "max_deliver", "deliver_policy", "opt_start_seq"):
            actual, expected = getattr(info.config, field), getattr(config, field)
            if field == "opt_start_seq" and not actual and not expected:
                continue
            if actual != expected:
                raise ValueError(f"consumer {spec.durable}: incompatible {field}; use a new durable for replay")
        if set(info.config.filter_subjects or [info.config.filter_subject]) != set(filters):
            raise ValueError("consumer filter mismatch")
        sub = await self.js.pull_subscribe_bind(durable=spec.durable, stream=spec.stream)
        self._subscriptions[spec.durable], self._specs[spec.durable] = sub, spec

    async def fetch(self, durable: str, batch: int = 16, timeout: float = 1.0) -> tuple[DurableDelivery, ...]:
        from nats.errors import TimeoutError as NatsTimeout
        spec = self._specs[durable]
        if not 1 <= batch <= spec.batch_size or timeout <= 0:
            raise ValueError("invalid pull batch or timeout")
        # The server enforces max_ack_pending. Local expired handles must not block redelivery.
        try:
            messages = await self._subscriptions[durable].fetch(batch=batch, timeout=timeout)
        except (NatsTimeout, TimeoutError):
            return ()
        deliveries = []
        for message in messages:
            meta = message.metadata
            # Replace a superseded local handle when this same consumer redelivers an expired message.
            for handle, (name, old) in list(self._pending.items()):
                if name == durable and old.metadata.sequence.stream == meta.sequence.stream:
                    self._pending.pop(handle)
            handle = uuid.uuid4().hex
            try:
                event = EventEnvelope.model_validate_json(message.data)
                if subject_to_topic(message.subject) != event.topic:
                    raise ValueError("subject/envelope mismatch")
                key, error = event.event_id, None
            except Exception:
                event, key, error = None, hashlib.sha256(message.data).hexdigest(), "invalid envelope or subject"
            self._pending[handle] = (durable, message)
            deliveries.append(DurableDelivery(delivery_id=handle, stream=meta.stream, sequence=meta.sequence.stream,
                                               attempt=meta.num_delivered, message_key=key, event=event, error=error))
        return tuple(deliveries)

    def _message(self, delivery):
        try:
            return self._pending[delivery.delivery_id][1]
        except KeyError as exc:
            raise ValueError("delivery already settled or handle is foreign") from exc

    async def ack(self, delivery):
        await self._message(delivery).ack_sync()
        self._pending.pop(delivery.delivery_id)

    async def retry(self, delivery, delay=5.0):
        if delay < 0:
            raise ValueError("negative retry delay")
        await self._message(delivery).nak(delay=delay)
        self._pending.pop(delivery.delivery_id)

    async def progress(self, delivery):
        await self._message(delivery).in_progress()

    async def close(self):
        # Do not delete durable consumers; unacknowledged work must be recoverable after restart.
        await self.connection.drain()
        self._pending.clear()


async def connect_jetstream(
    servers=("nats://127.0.0.1:4222",),
    *,
    credentials=None,
    tls=None,
    token=None,
) -> JetStreamBroker:
    """Runtime connection only. Provision streams separately with administrator credentials.
    tls may be an ssl.SSLContext; credentials is a nats credentials file path, never an envelope field.
    """
    if token is not None and credentials is not None:
        raise ValueError(
            "Cannot configure both token and credentials-file authentication simultaneously."
        )
    try:
        import nats
    except ImportError as exc:
        raise RuntimeError("Install datamesh-agency-toolkit[nats]") from exc
    options = {"servers": list(servers), "allow_reconnect": True, "max_reconnect_attempts": 10}
    if credentials:
        options["user_credentials"] = credentials
    if tls:
        options["tls"] = tls
    if token is not None:
        options["token"] = token

    connection = await nats.connect(**options)
    return JetStreamBroker(connection, connection.jetstream())
