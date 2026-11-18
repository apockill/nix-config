"""wait.py: what wakes a job's waiter, against the stand-in agent."""

from __future__ import annotations

import re
import threading
import time
from typing import cast

import pytest
from agent_runner.client import Client, ClientError
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


def test_a_marker_from_before_doesnt_count(service: Service) -> None:
    service.start_session("m", "say NIX-DONE")
    service.wait_state("m", "idle")
    how = Waiting(every=0.05, timeout=0.5, idle=3600)
    assert wait(service.client, "m", how).lines == ["TIMEOUT"]
    custom = Waiting(marker=re.compile("^echo"), every=0.05, timeout=5, idle=3600)
    woken: list[Woken] = []
    waiter = threading.Thread(
        target=lambda: woken.append(wait(service.client, "m", custom)), daemon=True
    )
    waiter.start()
    time.sleep(0.3)
    service.call("POST", "/v1/sessions/m/send", {"text": "hi"})
    waiter.join(10)
    assert woken[0].lines == ["MARKER echo: hi"]


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


def test_quiet_counts_from_the_last_event() -> None:
    class Status:
        state = "idle"
        last_event_at = 1000.5
        reason = None
        pending: list[object] = []

    class Output:
        lines = ["x" * 300]

    class Fake:
        def output(self, name: str, lines: int) -> Output:
            return Output()

        def status(self, name: str) -> Status:
            return Status()

    clock = Clock(monotonic=lambda: 0.0, now=lambda: 1300.9, sleep=lambda s: None)
    woken = wait(cast(Client, Fake()), "j", Waiting(idle=300), clock)
    assert woken.lines == ["IDLE (idle, quiet 300s)", "x" * 200]


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
    assert wait(service.client, "slow", how).lines == ["TIMEOUT"]
    service.call("POST", "/v1/sessions/slow/cancel", {})


def test_woken() -> None:
    assert Woken([]).outcome == ""
    assert Woken(["IDLE (idle, quiet 3s)", "x"]).outcome == "IDLE"
    assert Woken(["ENDED stopped: why"]).outcome == "ENDED"


def test_woken_no_session_outcome() -> None:
    assert Woken(["ENDED: no session x"]).outcome == "ENDED"
