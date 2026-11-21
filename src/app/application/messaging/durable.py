"""Durable asynchronous messaging ports. Separate from the synchronous simulation broker.

A broker confirms storage, not business success. The worker commits its inbox marker, objects and outbox atomically,
then acknowledges delivery. All handlers must restrict side effects to that same unit of work.
"""
from __future__ import annotations

import asyncio
import hashlib
from datetime import datetime, timezone
from typing import Callable, Literal, Optional, Protocol

from pydantic import Field, model_validator

from app.application.common.contracts import _Frozen
from app.application.persistence.contracts import CommandRecord
from app.application.persistence.ports import UnitOfWork, UnitOfWorkFactory
from .contracts import EventEnvelope, make_event, valid_pattern


class PublishReceipt(_Frozen):
    stream: str = Field(min_length=1, description="Stream that durably accepted the event.")
    sequence: int = Field(ge=1, description="Stream sequence, not a business version.")
    duplicate: bool = Field(default=False, description="Duplicate within the broker's configured deduplication window.")


class DurableConsumerSpec(_Frozen):
    stream: str = Field(pattern=r"^[A-Z][A-Z0-9_]{0,63}$", description="Provisioned stream name.")
    durable: str = Field(pattern=r"^[A-Za-z][A-Za-z0-9_-]{0,63}$", description="Stable name shared by this worker pool.")
    pattern: str = Field(description="Slash-style filter; final # must follow at least one level.")
    batch_size: int = Field(default=16, ge=1, le=256, description="Maximum deliveries fetched at once.")
    max_ack_pending: int = Field(default=64, ge=1, le=10000, description="Shared in-flight cap across this consumer's workers.")
    ack_wait: float = Field(default=60.0, ge=1, description="Seconds before unacknowledged work is redelivered.")
    start_sequence: Optional[int] = Field(default=None, ge=1, description="Replay start, on NEW consumers only; existing progress wins.")

    @model_validator(mode="after")
    def _rules(self):
        if not valid_pattern(self.pattern) or self.pattern == "#":
            raise ValueError("use an explicit stream filter, such as raw/#")
        if self.max_ack_pending < self.batch_size:
            raise ValueError("max_ack_pending must be at least batch_size")
        return self


class DurableDelivery(_Frozen):
    delivery_id: str = Field(description="Opaque adapter handle for this delivery attempt.")
    stream: str = Field(description="Origin stream.")
    sequence: int = Field(ge=1, description="Origin sequence.")
    attempt: int = Field(ge=1, description="Delivery count, including retries.")
    message_key: str = Field(pattern=r"^[0-9a-f]{64}$", description="Validated event id or digest of invalid input bytes.")
    event: Optional[EventEnvelope] = Field(default=None, description="Validated event, absent for malformed input.")
    error: Optional[str] = Field(default=None, description="Safe validation failure category; never raw payload.")


class DurableBrokerPort(Protocol):
    async def publish(self, event: EventEnvelope) -> PublishReceipt: ...
    async def ensure_consumer(self, spec: DurableConsumerSpec) -> None: ...
    async def fetch(self, durable: str, batch: int = 16, timeout: float = 1.0) -> tuple[DurableDelivery, ...]: ...
    async def ack(self, delivery: DurableDelivery) -> None: ...
    async def retry(self, delivery: DurableDelivery, delay: float = 5.0) -> None: ...
    async def progress(self, delivery: DurableDelivery) -> None: ...
    async def close(self) -> None: ...


def inbox_key(handler_id: str, message_key: str) -> str:
    """Persistent worker marker identity, also used by read-only status queries."""
    return "inbox:" + hashlib.sha256(f"{handler_id}:{message_key}".encode()).hexdigest()


# Compatibility alias for one release; persisted keys are unchanged.
_inbox_key = inbox_key


class TransactionalWorker:
    """One sequential batch per invocation. Distinct durable names fan out; identical names share work.

    A handler writes only through its UoW. Never perform external mutations here: put those requests in the outbox.
    Persistent inbox deduplication is scoped by handler_id (change it deliberately for a new projection generation).
    """
    def __init__(self, broker: DurableBrokerPort, uow_factory: UnitOfWorkFactory, spec: DurableConsumerSpec,
                 handler_id: str, handler: Callable[[UnitOfWork, EventEnvelope], Literal["applied", "rejected"] | None], max_attempts: int = 5,
                 retry_delay: float = 5.0):
        if not handler_id or max_attempts < 1 or retry_delay < 0:
            raise ValueError("needs handler identity, positive max_attempts, nonnegative delay")
        self.broker, self.uow_factory, self.spec = broker, uow_factory, spec
        self.handler_id, self.handler = handler_id, handler
        self.max_attempts, self.retry_delay = max_attempts, retry_delay

    def _apply(self, delivery: DurableDelivery, terminal_reason: Optional[str] = None):
        key = inbox_key(self.handler_id, delivery.message_key)
        with self.uow_factory() as uow:
            if uow.commands.get(key) is not None:
                return
            at = datetime.now(timezone.utc)
            outcome = "rejected" if terminal_reason else "applied"
            if terminal_reason:
                # A durable quarantine event is committed BEFORE the source delivery is acknowledged.
                event = make_event(topic="quarantine/broker/" + self.spec.durable, kind="ingest.rejection",
                                   source="durable-worker", epistemic_status="computed", occurred_at=at,
                                   causation_id=delivery.event.event_id if delivery.event else None,
                                   payload={"reason": terminal_reason, "stream": delivery.stream,
                                            "sequence": delivery.sequence, "message_key": delivery.message_key,
                                            "handler_id": self.handler_id, "attempt": delivery.attempt})
                uow.outbox.add(event, at)
            else:
                result = self.handler(uow, delivery.event)
                # None preserves existing handlers. Rejection events are staged
                # by the handler in this same UoW, never re-created by the worker.
                if result not in (None, "applied", "rejected"):
                    raise ValueError("invalid durable handler outcome")
                if result == "rejected":
                    outcome = "rejected"
            uow.commands.record(CommandRecord(command_id=key, command_type="broker.inbox", recorded_at=at,
                                               outcome=outcome,
                                               detail=terminal_reason))
            uow.commit()

    async def _heartbeat(self, delivery):
        while True:
            await asyncio.sleep(self.spec.ack_wait / 3)
            await self.broker.progress(delivery)

    async def process(self, delivery: DurableDelivery) -> None:
        heartbeat = asyncio.create_task(self._heartbeat(delivery))
        try:
            try:
                await asyncio.to_thread(self._apply, delivery, "invalid envelope" if delivery.event is None else None)
            except Exception as exc:
                # Failed transaction rolled back. Never leak credentials or document text from exception strings.
                if delivery.attempt >= self.max_attempts:
                    await asyncio.to_thread(self._apply, delivery, "retry budget exhausted: " + type(exc).__name__)
                else:
                    await self.broker.retry(delivery, self.retry_delay)
                    return
            # Ack failure propagates; a replay is safe because the inbox marker has already committed.
            await self.broker.ack(delivery)
        finally:
            heartbeat.cancel()
            try:
                await heartbeat
            except asyncio.CancelledError:
                pass

    async def run_batch(self, timeout: float = 1.0) -> int:
        deliveries = await self.broker.fetch(self.spec.durable, self.spec.batch_size, timeout)
        # Heartbeat every fetched item, including those waiting behind a slower predecessor.
        beats = [asyncio.create_task(self._heartbeat(d)) for d in deliveries]
        try:
            for delivery in deliveries:
                await self.process(delivery)
        finally:
            for beat in beats:
                beat.cancel()
            await asyncio.gather(*beats, return_exceptions=True)
        return len(deliveries)


async def relay_durable_outbox(uow_factory: UnitOfWorkFactory, broker: DurableBrokerPort,
                               at: datetime, limit: int = 100) -> int:
    """Mark only events with a storage confirmation. Partial failure leaves the remainder pending for replay."""
    with uow_factory() as uow:
        pending = uow.outbox.pending(limit)
    sent = 0
    for entry in pending:
        await broker.publish(EventEnvelope.model_validate(entry.envelope))
        with uow_factory() as uow:
            uow.outbox.mark_published((entry.event_id,), at)
            uow.commit()
        sent += 1
    return sent


DURABLE_CONTRACTS = (PublishReceipt, DurableConsumerSpec, DurableDelivery)
