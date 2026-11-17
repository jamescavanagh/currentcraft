"""Synchronous local/simulation broker port. Network durability lives in messaging.durable.DurableBrokerPort."""

from __future__ import annotations

from typing import Callable, Protocol, runtime_checkable

from .contracts import EventEnvelope

Handler = Callable[[EventEnvelope], None]


@runtime_checkable
class MessageBrokerPort(Protocol):
    def publish(self, event: EventEnvelope) -> bool:
        """Deliver to matching subscribers; False if the event_id was already published."""
        ...

    def subscribe(self, pattern: str, handler: Handler) -> str:
        """Register a handler for an MQTT-style pattern; returns a subscription id."""
        ...

    def unsubscribe(self, subscription_id: str) -> None: ...

    def replay(self, pattern: str = "#", from_offset: int = 0) -> tuple[EventEnvelope, ...]:
        """Events matching pattern in publish order, starting at a log offset."""
        ...
