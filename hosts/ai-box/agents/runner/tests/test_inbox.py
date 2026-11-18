"""inbox.py: what a session does with the agent's requests and notifications."""

from __future__ import annotations

import json
from typing import Any

import pytest
from agent_runner.client import ClientError
from conftest import Service, wait_for


def kinds(events: list[dict[str, Any]], *wanted: str) -> list[dict[str, Any]]:
    return [e for e in events if e["kind"] in wanted]


def test_a_malformed_request_is_refused_loudly(service: Service) -> None:
    service.start_session("m", "malformed")
    done = service.wait_state("m", "idle")
    answer = json.loads(done["last_message"].removeprefix("malformed: "))
    assert answer["code"] == -32602 and "optionId: missing" in answer["message"]
    [error] = kinds(service.events("m"), "error")
    assert "session/request_permission that doesn't fit ACP" in error["message"]
    assert not kinds(service.events("m"), "permission")
    assert done["pending"] == []


def test_an_unknown_request_is_answered_method_not_found(service: Service) -> None:
    service.start_session("u", "unknown")
    done = service.wait_state("u", "idle")
    answer = json.loads(done["last_message"].removeprefix("unknown: "))
    assert answer["code"] == -32601
    assert answer["message"] == "agent-runner doesn't implement fs/read_text_file"


def test_other_notifications_become_events(service: Service) -> None:
    service.start_session("n", "notify")
    service.wait_state("n", "idle")
    [note] = wait_for(lambda: kinds(service.events("n"), "notification"))
    assert note["method"] == "auth/status_update" and note["params"] == {"ok": True}


def test_the_agent_withdraws_its_request(service: Service) -> None:
    service.start_session("w", "withdraw")
    resolved = wait_for(lambda: kinds(service.events("w"), "resolved"))
    assert resolved == [
        {
            **resolved[0],
            "request_id": "p1",
            "by": "agent",
            "answer": None,
        }
    ]
    assert "reason" not in resolved[0]
    states = [e["state"] for e in kinds(service.events("w"), "state")]
    assert "waiting" in states
    assert service.wait_state("w", "idle")["pending"] == []


def test_a_load_only_agent_resumes_with_its_history_muted(service: Service) -> None:
    service.start_session("l", "hello", agent="loadonly")
    service.wait_state("l", "idle")
    service.stop()
    service.start()
    assert service.status("l")["state"] == "offline"
    before = len(service.events("l"))
    assert service.call("POST", "/v1/sessions/l/send", {"text": "again"}) == {
        "delivery": "sent"
    }
    done = service.wait_state("l", "idle")
    assert done["last_message"] == "echo: again"
    after = service.events("l")[before:]
    texts = [
        e["update"]["content"]["text"]
        for e in kinds(after, "update")
        if "content" in e["update"]
    ]
    assert "history" not in texts and "echo: again" in texts
    assert [e["agent_session_id"] for e in kinds(after, "session")] == [
        done["agent_session_id"]
    ]


def test_answers_are_checked_against_the_request(service: Service) -> None:
    service.start_session("p", "permission")
    service.wait_state("p", "waiting")
    url = "/v1/sessions/p/requests/p1"
    for body, error in (
        ({"option_id": "maybe"}, "option_id must be one of allow, reject"),
        ({"option_id": "allow", "extra": 1}, "extra: unknown field"),
        ({"action": "accept"}, "action: unknown field"),
    ):
        with pytest.raises(ClientError, match=error) as e:
            service.call("POST", url, body)
        assert e.value.status == 400
    with pytest.raises(ClientError, match="p has no open request p9") as e:
        service.call("POST", "/v1/sessions/p/requests/p9", {"option_id": "allow"})
    assert e.value.status == 404
    # Still parked after the refusals.
    assert [p["request_id"] for p in service.status("p")["pending"]] == ["p1"]
    service.call("POST", url, {"option_id": "reject"})
    done = service.wait_state("p", "idle")
    assert (
        done["last_message"]
        == 'permission: {"outcome": "selected", "optionId": "reject"}'
    )


def test_a_question_needs_its_answer_in_form(service: Service) -> None:
    service.start_session("q", "question")
    service.wait_state("q", "waiting")
    url = "/v1/sessions/q/requests/q1"
    for body, error in (
        ({"action": "accept"}, "accept needs content"),
        ({"action": "maybe"}, "action: must be one of accept, decline, cancel"),
        ({"option_id": "allow"}, "option_id: unknown field"),
        ({"action": "accept", "content": []}, "content: must be an object"),
    ):
        with pytest.raises(ClientError, match=error):
            service.call("POST", url, body)
    service.call("POST", url, {"action": "accept", "content": {"colour": "red"}})
    assert service.wait_state("q", "idle")["last_message"] == (
        'question: {"action": "accept", "content": {"colour": "red"}}'
    )
