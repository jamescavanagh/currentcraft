"""Deterministic process-local test double for DurableBrokerPort. Not a persistent server or a NATS emulator.

Explicit virtual time makes retry/ack-expiry tests reproducible. Dedup is permanent here (JetStream is windowed).
"""
import uuid

from app.application.messaging.contracts import topic_matches
from app.application.messaging.durable import DurableDelivery, PublishReceipt
from .jetstream import STREAM_FAMILIES


class InMemoryDurableBroker:
    def __init__(self):
        self.logs = {name: [] for name in STREAM_FAMILIES}
        self.specs, self.acked, self.pending, self.attempts, self.delays, self.seen = {}, {}, {}, {}, {}, {}
        self.now = 0.0
        self.closed = False

    def advance(self, seconds):
        self.now += seconds

    async def publish(self, event):
        family = event.topic.split('/')[0]
        stream = next((s for s, fs in STREAM_FAMILIES.items() if family in fs), None)
        if stream is None:
            raise ValueError('unrouted topic family')
        if event.event_id in self.seen:
            s, seq = self.seen[event.event_id]
            return PublishReceipt(stream=s, sequence=seq, duplicate=True)
        self.logs[stream].append(event)
        seq = len(self.logs[stream])
        self.seen[event.event_id] = (stream, seq)
        return PublishReceipt(stream=stream, sequence=seq)

    async def ensure_consumer(self, spec):
        if spec.stream not in self.logs:
            raise ValueError('unknown stream')
        if spec.durable in self.specs and self.specs[spec.durable] != spec:
            raise ValueError('consumer configuration mismatch')
        self.specs[spec.durable] = spec
        self.acked.setdefault(spec.durable, set())

    async def fetch(self, durable, batch=16, timeout=1.0):
        spec = self.specs[durable]
        if not 1 <= batch <= spec.batch_size or timeout <= 0:
            raise ValueError('invalid batch or timeout')
        for handle, (name, seq, expiry, _) in list(self.pending.items()):
            if expiry <= self.now:
                self.pending.pop(handle)
        active = {seq for name, seq, _, _ in self.pending.values() if name == durable}
        room = spec.max_ack_pending - len(active)
        out = []
        for seq, event in enumerate(self.logs[spec.stream], 1):
            if seq < (spec.start_sequence or 1) or seq in active or seq in self.acked[durable]:
                continue
            if not topic_matches(spec.pattern, event.topic) or self.delays.get((durable, seq), 0) > self.now:
                continue
            if len(out) >= min(batch, room):
                break
            key = (durable, seq)
            attempt = self.attempts.get(key, 0) + 1
            self.attempts[key] = attempt
            handle = uuid.uuid4().hex
            d = DurableDelivery(delivery_id=handle, stream=spec.stream, sequence=seq, attempt=attempt,
                                message_key=event.event_id, event=event)
            self.pending[handle] = (durable, seq, self.now + spec.ack_wait, d)
            out.append(d)
        return tuple(out)

    async def ack(self, delivery):
        name, seq, _, _ = self.pending.pop(delivery.delivery_id)
        self.acked[name].add(seq)

    async def retry(self, delivery, delay=5.0):
        if delay < 0:
            raise ValueError('negative delay')
        name, seq, _, _ = self.pending.pop(delivery.delivery_id)
        self.delays[(name, seq)] = self.now + delay

    async def progress(self, delivery):
        name, seq, _, d = self.pending[delivery.delivery_id]
        self.pending[delivery.delivery_id] = (name, seq, self.now + self.specs[name].ack_wait, d)

    async def close(self):
        self.closed = True
