"""The events of every session: numbered, logged, kept in a ring, and fanned out to live streams."""

from __future__ import annotations

import asyncio
import contextlib
import time
from collections import deque
from collections.abc import AsyncIterator

from .config import RING_SIZE
from .events import Body, Event
from .store import SessionFiles


class EventBus:
    def __init__(self, ring_size: int = RING_SIZE) -> None:
        # The latest event's seq: seq increases across all sessions and runner restarts.
        self.seq = 0
        self.ring: deque[Event] = deque(maxlen=ring_size)
        self.subscribers: set[asyncio.Queue[Event]] = set()

    def advance(self, seq: int) -> None:
        """Continue after an event logged before this runner started."""
        self.seq = max(self.seq, seq)

    def publish(self, session: str, files: SessionFiles, body: Body) -> Event:
        self.seq += 1
        event = Event(seq=self.seq, ts=time.time(), session=session, body=body)
        files.append(event)
        self.ring.append(event)
        for queue in list(self.subscribers):
            queue.put_nowait(event)
        return event

    def recent(self, since: int) -> list[Event]:
        """The ring's events after `since` (the last RING_SIZE of all sessions)."""
        return [e for e in self.ring if e.seq > since]

    @contextlib.asynccontextmanager
    async def subscribe(self) -> AsyncIterator[asyncio.Queue[Event]]:
        """A queue that gets every event published while the context is open."""
        queue: asyncio.Queue[Event] = asyncio.Queue()
        self.subscribers.add(queue)
        try:
            yield queue
        finally:
            self.subscribers.discard(queue)
