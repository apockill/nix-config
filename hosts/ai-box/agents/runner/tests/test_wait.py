"""wait.py: what wakes a job's waiter, against the stand-in agent."""

from __future__ import annotations

import re
import threading
import time
from collections.abc import Iterator
from typing import cast

import pytest
from acp.schema import AgentMessageChunk, TextContentBlock
from agent_runner.client import Client, ClientError
from agent_runner.events import Event, Updated
from agent_runner.store import Limit
from agent_runner.wait import DEFAULT_MARKER, Clock, Waiting, Woken, wait
from conftest import Service

QUICK = Waiting(every=0.05, timeout=10, idle=3600)


def test_the_default_marker() -> None:
    marker = re.compile(DEFAULT_MARKER)
    for line in (
        "NIX-DONE",
        "NIX-DONE: all good",
        "SITES-2-NEED-LIVE",
        "X-RESTART-PLEASE  ",
    ):
        assert marker.search(line), line
    for line in ("> say NIX-DONE", "nix-DONE", "NIX-DONE now", "DONE", "the NIX-DONE"):
        assert not marker.search(line), line


def test_a_marker_line_wakes_it(service: Service) -> None:
    service.start_session("m")
    woken: list[Woken] = []
    waiter = threading.Thread(
        target=lambda: woken.append(wait(service.client, "m", QUICK)), daemon=True
    )
    waiter.start()
    time.sleep(0.3)
    service.call("POST", "/v1/sessions/m/send", {"text": "say NIX-DONE: shipped"})
    waiter.join(10)
    assert woken[0].lines == ["MARKER NIX-DONE: shipped"]
    assert woken[0].outcome == "MARKER"


def test_a_marker_since_the_last_prompt_counts(service: Service) -> None:
    # Printed before the waiter started (a short job, done inside start's wait): it counts.
    service.start_session("m", "say NIX-DONE")
    service.wait_state("m", "idle")
    how = Waiting(every=0.05, timeout=0.5, idle=3600)
    assert wait(service.client, "m", how).lines == ["MARKER NIX-DONE"]
    # A later prompt starts over: the marker of the turn before doesn't count.
    service.call("POST", "/v1/sessions/m/send", {"text": "hello"})
    service.wait_state("m", "idle")
    [line] = wait(service.client, "m", how).lines
    assert line.startswith("TIMEOUT after 0s: m is still idle; nothing watches it now")
    custom = Waiting(marker=re.compile("^echo"), every=0.05, timeout=5, idle=3600)
    assert wait(service.client, "m", custom).lines == ["MARKER echo: hello"]


def test_a_prompt_naming_the_marker_isnt_one(service: Service) -> None:
    unanchored = Waiting(marker=re.compile("DONE"), every=0.05, timeout=0.5, idle=3600)
    service.start_session("n", "say nothing yet, then DONE")
    service.wait_state("n", "idle")
    assert wait(service.client, "n", unanchored).lines == [
        "MARKER nothing yet, then DONE"
    ]
    service.call("POST", "/v1/sessions/n/send", {"text": "hello DONE?"})
    service.wait_state("n", "idle")
    # "> hello DONE?" is the prompt; only "echo: hello DONE?" is the agent's.
    assert wait(service.client, "n", unanchored).lines == ["MARKER echo: hello DONE?"]


def test_a_request_wakes_it(service: Service) -> None:
    service.start_session("p", "permission")
    woken = wait(service.client, "p", QUICK)
    assert woken.lines[:2] == ["WAITING", "p1 permission: touch x"]
    assert woken.lines[-1] == "[permission p1] touch x (allow, reject)"


def test_quiet_wakes_it(service: Service) -> None:
    service.start_session("i", "hello")
    service.wait_state("i", "idle")
    woken = wait(service.client, "i", Waiting(every=0.05, timeout=5, idle=0))
    assert re.fullmatch(r"IDLE \(idle, quiet \d+s\)", woken.lines[0])
    assert woken.lines[1:] == ["> hello", "echo: hello", "[turn ended: end_turn]"]


class Status:
    state = "idle"
    last_event_at = 1000.5
    reason = None
    pending: list[object] = []
    limit: Limit | None = None


class FakeClient:
    """A runner that says `Status`, whose session said "x" * 300; `down` calls fail as an
    unreachable runner does."""

    def __init__(self, down: int = 0, status: Status | None = None) -> None:
        self.down = down
        self.said = Status() if status is None else status
        self.calls = 0

    def status(self, name: str) -> Status:
        self.calls += 1
        if self.calls <= self.down:
            raise ClientError("the runner isn't running")
        return self.said

    def events(self, path: str) -> Iterator[Event]:
        chunk = AgentMessageChunk(
            session_update="agent_message_chunk",
            content=TextContentBlock(type="text", text="x" * 300),
        )
        update = Updated(update=chunk.model_dump(mode="json", by_alias=True))
        yield Event(seq=1, ts=1000.5, session="j", body=update)


def test_quiet_counts_from_the_last_event() -> None:
    clock = Clock(monotonic=lambda: 0.0, now=lambda: 1300.9, sleep=lambda s: None)
    woken = wait(cast(Client, FakeClient()), "j", Waiting(idle=300), clock)
    assert woken.lines == ["IDLE (idle, quiet 300s)", "x" * 200]


def ticking() -> Clock:
    """A clock whose sleeps pass time."""
    t = [0.0]

    def sleep(seconds: float) -> None:
        t[0] += seconds

    return Clock(monotonic=lambda: t[0], now=lambda: 1300.9, sleep=sleep)


def test_it_reconnects_while_the_runner_restarts() -> None:
    fake = FakeClient(down=5)
    woken = wait(cast(Client, fake), "j", Waiting(idle=300, every=15), ticking())
    assert woken.outcome == "IDLE" and fake.calls == 6


def test_it_gives_up_on_a_runner_gone_for_good() -> None:
    fake = FakeClient(down=100)
    with pytest.raises(ClientError, match=r"isn't running \(for over 120 s\)"):
        wait(cast(Client, fake), "j", Waiting(idle=300, every=15), ticking())
    assert fake.calls == 10


def test_a_limit_wakes_it() -> None:
    limited = Status()
    limited.state = "limited"
    limited.limit = Limit(resets_at=1795010400.0, kind="five_hour")
    woken = wait(cast(Client, FakeClient(status=limited)), "j", Waiting(), ticking())
    assert woken.lines[0].startswith(
        "LIMITED 1795010400 usage limit (five_hour) until "
    )
    assert woken.lines[1:] == ["x" * 200]
    # Offline after a runner restart, the limit still on: still LIMITED.
    limited.state = "offline"
    woken = wait(cast(Client, FakeClient(status=limited)), "j", Waiting(), ticking())
    assert woken.outcome == "LIMITED"
    limited.state = "limited"
    limited.limit = Limit()
    woken = wait(cast(Client, FakeClient(status=limited)), "j", Waiting(), ticking())
    assert woken.lines[0] == (
        "LIMITED unknown usage limit until an unknown time (the agent didn't say)"
    )


def test_the_end_wakes_it(service: Service) -> None:
    service.start_session("s", "hello")
    service.wait_state("s", "idle")
    service.call("POST", "/v1/sessions/s/stop", {"reason": "enough"})
    assert wait(service.client, "s", QUICK).lines == ["ENDED stopped: enough"]
    with pytest.raises(ClientError):
        service.start_session("f", "hello", agent="nosignin")
    [line] = wait(service.client, "f", QUICK).lines
    assert line.startswith("ENDED failed: the nosignin sign-in is missing or expired")
    assert wait(service.client, "ghost", QUICK).lines == ["ENDED: no session ghost"]


def test_a_running_turn_times_out(service: Service) -> None:
    service.start_session("slow", "slow")
    how = Waiting(every=0.05, timeout=0.5, idle=0)
    assert wait(service.client, "slow", how).lines == [
        "TIMEOUT after 0s: slow is still running; nothing watches it now:"
        " run `agent wait slow` again, or `agent stop slow`"
    ]
    service.call("POST", "/v1/sessions/slow/cancel", {})


def test_woken() -> None:
    assert Woken([]).outcome == ""
    assert Woken(["IDLE (idle, quiet 3s)", "x"]).outcome == "IDLE"
    assert Woken(["ENDED stopped: why"]).outcome == "ENDED"


def test_woken_no_session_outcome() -> None:
    assert Woken(["ENDED: no session x"]).outcome == "ENDED"
