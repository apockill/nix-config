"""session.py: opening, models, turns, questions answered, cancel, stop, the record."""

from __future__ import annotations

import json
from typing import Any

import pytest
from agent_runner.client import ClientError
from conftest import Service


def kinds(events: list[dict[str, Any]], *wanted: str) -> list[dict[str, Any]]:
    return [e for e in events if e["kind"] in wanted]


def test_a_model_given_as_a_config_option(service: Service) -> None:
    # Claude's way: any model goes to session/set_config_option; the agent decides.
    s = service.start_session("c", "hello", agent="configmodel", model="opus")
    assert s["model"] == "opus"
    assert service.wait_state("c", "idle")["last_message"] == "echo: hello"


def test_states_through_a_turn_and_a_question(service: Service) -> None:
    service.start_session("q", "question")
    pending = service.wait_state("q", "waiting")["pending"]
    assert [p["request_id"] for p in pending] == ["q1"]
    service.call("POST", "/v1/sessions/q/requests/q1", {"action": "decline"})
    done = service.wait_state("q", "idle")
    assert done["last_message"] == 'question: {"action": "decline"}'
    states = [e["state"] for e in kinds(service.events("q"), "state")]
    assert states == ["idle", "running", "waiting", "running", "idle"]
    [resolved] = kinds(service.events("q"), "resolved")
    assert resolved["by"] == "client" and resolved["answer"] == {"action": "decline"}


def test_cancel_cancels_open_requests(service: Service) -> None:
    service.start_session("p", "permission")
    service.wait_state("p", "waiting")
    service.call("POST", "/v1/sessions/p/cancel", {})
    done = service.wait_state("p", "idle")
    assert done["last_message"] == 'permission: {"outcome": "cancelled"}'
    assert kinds(service.events("p"), "cancel")


def test_stop_drops_open_requests(service: Service) -> None:
    service.start_session("s", "permission")
    service.wait_state("s", "waiting")
    service.call("POST", "/v1/sessions/s/stop", {"reason": "enough"})
    s = service.status("s")
    assert (s["state"], s["reason"], s["pending"], s["alive"]) == (
        "stopped",
        "enough",
        [],
        False,
    )
    [resolved] = kinds(service.events("s"), "resolved")
    assert (resolved["by"], resolved["reason"]) == ("runner", "stopped")


def test_the_session_record_follows_the_session(service: Service) -> None:
    service.start_session("r", "hello", env={"X": "secret"}, origin="test")
    service.wait_state("r", "idle")
    record = json.loads((service.state / "sessions/r/session.json").read_text())
    # The record keeps the values (for resumes); the API names them only.
    assert record["env"] == {"X": "secret"} and service.status("r")["env"] == ["X"]
    assert record["origin"] == "test" and record["turns"] == 1
    assert record["state"] == "idle"
    assert (service.state / "sessions/r/agent.log").exists()


def test_stopping_the_runner_leaves_sessions_resumable(service: Service) -> None:
    service.start_session("o", "hello")
    service.wait_state("o", "idle")
    service.stop()
    service.start()
    s = service.status("o")
    assert (s["state"], s["alive"]) == ("offline", False)
    assert s["reason"] == "the runner stopped; a message resumes it"
    assert service.call("POST", "/v1/sessions/o/send", {"text": "again"}) == {
        "delivery": "sent"
    }
    assert service.wait_state("o", "idle")["last_message"] == "echo: again"


def test_a_session_that_never_started_cant_be_resumed(service: Service) -> None:
    with pytest.raises(ClientError, match="sign-in is missing or expired"):
        service.start_session("n", agent="nosignin")
    s = service.status("n")
    assert s["state"] == "failed" and s["agent_session_id"] is None
    with pytest.raises(ClientError, match="never started") as e:
        service.call("POST", "/v1/sessions/n/send", {"text": "x"})
    assert e.value.status == 409


def test_a_failed_model_keeps_the_session_resumable(service: Service) -> None:
    with pytest.raises(ClientError, match="no model 'huge'; it has: big, small"):
        service.start_session("m", "hello", model="huge")
    s = service.status("m")
    # The agent's session was created before the model failed: a message resumes it.
    assert s["state"] == "failed" and s["agent_session_id"]
    [error] = [e for e in service.events("m") if e["kind"] == "error"]
    assert "no model 'huge'" in error["message"]
