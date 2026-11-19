"""turns.py: how turns fail (usage limits, repeats), the queue across restarts, and what the
runner tells Alex; against the stand-in agent, which fails turns as claude-agent-acp does.
"""

from __future__ import annotations

import time
from collections.abc import Iterator
from pathlib import Path

import pytest
from agent_runner.client import ClientError
from conftest import AGENTS, Service, fake_agent, wait_for


def notified(service: Service) -> list[str]:
    path = service.notified
    return path.read_text().splitlines() if path.exists() else []


def refused(
    service: Service, method: str, path: str, body: object = None
) -> ClientError:
    with pytest.raises(ClientError) as e:
        service.call(method, path, body)
    return e.value


def test_a_usage_limit_fails_the_start_with_429_and_its_reset(service: Service) -> None:
    resets = int(time.time()) + 3600
    e = refused(
        service,
        "POST",
        "/v1/sessions",
        {"name": "l", "dir": str(service.tmp), "task": f"limit {resets}"},
    )
    assert (e.status, e.resets_at) == (429, float(resets))
    assert "l hit the usage limit (five_hour) until" in str(e)
    s = service.status("l")
    assert s["state"] == "limited" and s["reason"].startswith("usage limit (five_hour)")
    assert s["limit"] == {"resets_at": float(resets), "kind": "five_hour"}
    [error] = [e for e in service.events("l") if e["kind"] == "error"]
    assert error["error_kind"] == "rate_limit"
    assert error["data"]["rateLimit"]["resetsAt"] == resets
    # Sends are refused until the reset, with it.
    e = refused(service, "POST", "/v1/sessions/l/send", {"text": "again"})
    assert (e.status, e.resets_at) == (429, float(resets))
    # Alex hears once per reset, whichever session hits it.
    wait_for(lambda: notified(service))
    service.start_session("m")
    service.call("POST", "/v1/sessions/m/send", {"text": f"limit {resets}"})
    service.wait_state("m", "limited")
    time.sleep(0.3)
    [message] = notified(service)
    assert message.startswith(
        "agent-runner: fake hit its usage limit (five_hour) until"
    )
    assert "session l is limited (sends are refused until then)" in message


def test_a_limit_ends_by_itself_at_the_reset(service: Service) -> None:
    service.start_session("l")
    service.call(
        "POST", "/v1/sessions/l/send", {"text": f"limit {int(time.time()) + 2}"}
    )
    service.wait_state("l", "limited")
    assert service.wait_state("l", "idle")["limit"] is not None
    assert service.call("POST", "/v1/sessions/l/send", {"text": "hello"}) == {
        "delivery": "sent"
    }
    s = service.wait_state("l", "idle")
    assert s["limit"] is None and s["last_message"] == "echo: hello"


def test_a_limit_without_a_reset_time(service: Service) -> None:
    service.start_session("u")
    service.call("POST", "/v1/sessions/u/send", {"text": "limit-unknown"})
    s = service.wait_state("u", "limited")
    assert s["limit"] == {"resets_at": None, "kind": None}
    assert s["reason"] == "usage limit until an unknown time (the agent didn't say)"
    # Nothing says when, so a send may try; a turn that ends well clears it.
    service.call("POST", "/v1/sessions/u/send", {"text": "hello"})
    assert service.wait_state("u", "idle")["limit"] is None


def test_repeated_failures_are_told_once(service: Service) -> None:
    service.start_session("f")
    for _ in range(4):
        service.call("POST", "/v1/sessions/f/send", {"text": "fail"})
        service.wait_state("f", "idle")
    errors = [e for e in service.events("f") if e["kind"] == "error"]
    assert len(errors) == 4 and {e["error_kind"] for e in errors} == {"server_error"}
    assert service.status("f")["failed_turns"] == 4
    [message] = wait_for(lambda: notified(service))
    assert message.startswith("agent-runner: session f (fake): its last 3 turns failed")
    service.call("POST", "/v1/sessions/f/send", {"text": "hello"})
    assert service.wait_state("f", "idle")["failed_turns"] == 0


def test_queued_messages_survive_a_runner_restart_and_go_first(
    service: Service,
) -> None:
    service.start_session("q", "slow")
    service.wait_state("q", "running")
    assert service.call("POST", "/v1/sessions/q/send", {"text": "first"}) == {
        "delivery": "queued"
    }
    e = refused(service, "POST", "/v1/restart", {})
    assert e.status == 409 and "q would lose their running turn" in str(e)
    service.call("POST", "/v1/restart", {"force": True})
    assert service.thread
    service.thread.join(20)
    assert service.exit_code == 75
    service.start()
    s = service.status("q")
    assert s["state"] == "offline" and s["queued"] == ["first"]
    assert "during a turn" in s["reason"]
    wait_for(
        lambda: any(
            "the runner stopped during the turns of q" in m for m in notified(service)
        )
    )
    # A new message resumes the session; the one queued before it goes first.
    assert service.call("POST", "/v1/sessions/q/send", {"text": "second"}) == {
        "delivery": "queued"
    }
    wait_for(lambda: service.status("q")["last_message"] == "echo: second")
    sent = [
        e["text"]
        for e in service.events("q")
        if e["kind"] == "prompt" and e["delivery"] == "sent"
    ]
    assert sent == ["slow", "first", "second"]
    assert service.status("q")["queued"] == []


def test_the_compaction_window_is_recorded(service: Service) -> None:
    # None set: the agent's own default, and nothing recorded.
    service.start_session("w", agent="windowed")
    assert service.status("w")["compact_window"] is None
    # The caller's (Sculpt's builders set 200k).
    service.start_session("v", agent="windowed", env={"WINDOW": "200000"})
    assert service.status("v")["compact_window"] == 200000
    service.start_session("n")
    assert service.status("n")["compact_window"] is None


@pytest.fixture
def strict(tmp_path: Path) -> Iterator[Service]:
    """A runner that tells Alex of a request left unanswered after 0.5 s, and runs its agents
    with umask 0027."""
    s = Service(
        tmp_path,
        {
            "default": "fake",
            "agents": {"fake": fake_agent(), **AGENTS},
            "parked_notify_seconds": 0.5,
            "agent_umask": "0027",
        },
    )
    s.start()
    yield s
    s.stop()


def test_an_unanswered_request_is_told(strict: Service) -> None:
    strict.start_session("p", "permission")
    [message] = wait_for(lambda: notified(strict))
    assert message == (
        "agent-runner: session p has waited 0 s for an answer to its permission p1:"
        " touch x (agent peek p; agent answer p p1 ...)"
    )
    strict.call("POST", "/v1/sessions/p/requests/p1", {"option_id": "allow"})
    strict.wait_state("p", "idle")
    # Answered in time: nothing told.
    strict.call("POST", "/v1/sessions/p/send", {"text": "permission"})
    strict.wait_state("p", "waiting")
    strict.call("POST", "/v1/sessions/p/requests/p2", {"option_id": "allow"})
    time.sleep(0.8)
    assert len(notified(strict)) == 1


def test_agents_run_with_the_agent_umask(strict: Service) -> None:
    strict.start_session("u", "umask")
    assert strict.wait_state("u", "idle")["last_message"] == "umask 0027"
