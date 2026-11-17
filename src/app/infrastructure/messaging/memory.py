"""In-memory broker: append-only log, MQTT-style matching, FIFO delivery, idempotent publish, dead letters."""

from __future__ import annotations

from collections import deque
from itertools import count

from app.application.messaging.contracts import EventEnvelope, topic_matches, valid_pattern


class InMemoryBroker:
    def __init__(self) -> None:
        self.log: list[EventEnvelope] = []
        self.dead_letters: list[tuple[EventEnvelope, str, str]] = []
        self._seen: set[str] = set()
        self._subs: dict[str, tuple[str, object]] = {}
        self._ids = count(1)
        self._queue: deque[EventEnvelope] = deque()
        self._delivering = False

    def publish(self, event: EventEnvelope) -> bool:
        if not isinstance(event, EventEnvelope):
            raise TypeError("publish EventEnvelope instances")
        if event.event_id in self._seen:
            return False
        self._seen.add(event.event_id)
        self.log.append(event)
        self._queue.append(event)
        if not self._delivering:
            self._delivering = True
            try:
                while self._queue:
                    ev = self._queue.popleft()
                    for sid, (pattern, handler) in list(self._subs.items()):
                        if topic_matches(pattern, ev.topic):
                            try:
                                handler(ev)
                            except Exception as exc:  # isolate subscribers
                                self.dead_letters.append((ev, sid, f"{type(exc).__name__}: {exc}"))
            finally:
                self._delivering = False
        return True

    def subscribe(self, pattern: str, handler) -> str:
        if not valid_pattern(pattern):
            raise ValueError(f"invalid subscribe pattern {pattern!r}")
        sid = f"sub-{next(self._ids)}"
        self._subs[sid] = (pattern, handler)
        return sid

    def unsubscribe(self, subscription_id: str) -> None:
        self._subs.pop(subscription_id, None)

    def replay(self, pattern: str = "#", from_offset: int = 0) -> tuple[EventEnvelope, ...]:
        if not valid_pattern(pattern):
            raise ValueError(f"invalid pattern {pattern!r}")
        return tuple(e for e in self.log[from_offset:] if topic_matches(pattern, e.topic))
