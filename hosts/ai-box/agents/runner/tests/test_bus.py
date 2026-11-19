"""Tests for bus.py: numbering, the ring, the log and the live subscribers."""

from __future__ import annotations

import asyncio
from pathlib import Path

from agent_runner.bus import EventBus
from agent_runner.events import Failed, StateChanged
from agent_runner.store import SessionFiles


def test_publish_numbers_logs_and_keeps_events(tmp_path: Path) -> None:
    bus = EventBus(ring_size=2)
    files = SessionFiles(tmp_path / "s")
    bus.advance(10)
    bus.advance(3)  # never backwards
    events = [bus.publish("s", files, Failed(message=str(i))) for i in range(3)]
    assert [e.seq for e in events] == [11, 12, 13]
    assert bus.seq == 13
    assert [e.seq for e in bus.recent(0)] == [12, 13]  # the ring holds two
    assert [e.seq for e in bus.recent(12)] == [13]
    assert [e.seq for e in files.read_events()] == [11, 12, 13]
    assert events[0].session == "s" and events[0].ts > 0


def test_subscribers_get_what_is_published_while_subscribed(tmp_path: Path) -> None:
    async def main() -> None:
        bus = EventBus()
        files = SessionFiles(tmp_path / "s")
        bus.publish("s", files, StateChanged(state="idle"))
        async with bus.subscribe() as first:
            async with bus.subscribe() as second:
                assert len(bus.subscribers) == 2
                event = bus.publish("s", files, StateChanged(state="running"))
            assert await first.get() == event
            assert await second.get() == event
            assert first.empty()
        assert bus.subscribers == set()

    asyncio.run(main())
