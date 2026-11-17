"""IngestRing: the buffer ring of the ingestion design (docs/architecture/INGESTION.md). Pure Python.

Bounded, per-consumer cursors, at-least-once delivery, backpressure instead of silent drops, idempotent appends.
"""

from __future__ import annotations

from collections import OrderedDict

from .contracts import DomainObject, RingEntry


class RingFull(RuntimeError):
    """The ring is full and its oldest entry is still needed by a consumer."""


class IngestRing:
    """Bounded ring of domain-object versions between ingestion and tensor consumers.

    Not the simulator's BufferRing (a tracer orbit) and not a project buffer resource.
    """
    def __init__(self, capacity: int):
        if capacity < 1:
            raise ValueError("capacity must be positive")
        self.capacity = capacity
        self._entries: "OrderedDict[int, RingEntry]" = OrderedDict()
        self._next = 0
        self._cursor: dict[str, int] = {}      # next offset to deliver
        self._committed: dict[str, int] = {}   # next offset not yet committed
        self._kinds: dict[str, tuple[str, ...]] = {}
        self._latest: dict[str, str] = {}      # object_id -> digest of latest version

    # -- producers --------------------------------------------------------
    def append(self, obj: DomainObject) -> int | None:
        """Append a version; None if identical to the latest version of that object."""
        digest = obj.digest()
        if self._latest.get(obj.object_id) == digest:
            return None
        self.trim()
        if len(self._entries) >= self.capacity:
            raise RingFull(f"ring full ({self.capacity}); oldest offset {next(iter(self._entries))} not committed by all consumers")
        off = self._next
        self._entries[off] = RingEntry(offset=off, object=obj, digest=digest)
        self._latest[obj.object_id] = digest
        self._next += 1
        return off

    def trim(self) -> int:
        """Drop leading entries no registered consumer still needs. Without consumers nothing is dropped.

        An entry is still needed by a consumer when it is at or past that consumer's committed offset and of a kind
        the consumer reads. A consumer that filters kinds therefore never pins entries of other kinds.
        """
        if not self._committed:
            return 0
        n = 0
        while self._entries:
            off, e = next(iter(self._entries.items()))
            if any(self._needs(c, off, e) for c in self._committed):
                break
            self._entries.popitem(last=False)
            n += 1
        return n

    def _needs(self, name: str, off: int, e: RingEntry) -> bool:
        kinds = self._kinds[name]
        return off >= self._committed[name] and (not kinds or e.object.kind in kinds)

    def free(self) -> int:
        """Slots available after trimming."""
        self.trim()
        return self.capacity - len(self._entries)

    # -- consumers --------------------------------------------------------
    def register(self, name: str, kinds: tuple[str, ...] = ()) -> None:
        if name in self._cursor:
            if self._kinds[name] != tuple(kinds):
                raise ValueError(f"consumer {name!r} already registered with other kinds")
            return
        start = next(iter(self._entries)) if self._entries else self._next
        self._cursor[name] = self._committed[name] = start
        self._kinds[name] = tuple(kinds)

    def poll(self, name: str, max_entries: int) -> tuple[RingEntry, ...]:
        """Entries from the consumer's cursor (skipping other kinds). Redelivered until committed."""
        self._cursor[name] = self._committed[name]
        kinds = self._kinds[name]
        out = []
        for off, e in self._entries.items():
            if off < self._cursor[name]:
                continue
            if kinds and e.object.kind not in kinds:
                continue
            out.append(e)
            if len(out) >= max_entries:
                break
        return tuple(out)

    def commit(self, name: str, through_offset: int) -> None:
        """Mark everything up to and including through_offset as used by this consumer."""
        if through_offset >= self._next:
            raise ValueError("cannot commit past the ring head")
        self._committed[name] = max(self._committed[name], through_offset + 1)

    def lag(self, name: str) -> int:
        """Entries of this consumer's kinds appended but not yet committed."""
        kinds = self._kinds[name]
        return sum(1 for off, e in self._entries.items() if self._needs(name, off, e))

    def __len__(self) -> int:
        return len(self._entries)

    @property
    def head(self) -> int:
        return self._next
