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
    assert answer["code"] == -32602 and answer["message"] == "Invalid params"
    wrong = {".".join(map(str, e["loc"])) for e in answer["data"]["errors"]}
    assert "options.0.optionId" in wrong
    [error] = kinds(service.events("m"), "error")
    assert "session/request_permission that doesn't fit ACP" in error["message"]
    assert "options.0.optionId: Field required" in error["message"]
    assert not kinds(service.events("m"), "permission")
    assert done["pending"] == []


def test_an_unknown_request_is_answered_method_not_found(service: Service) -> None:
    service.start_session("u", "unknown")
    done = service.wait_state("u", "idle")
    answer = json.loads(done["last_message"].removeprefix("unknown: "))
    assert answer["code"] == -32601 and answer["message"] == "Method not found"
    assert answer["data"] == {"method": "fs/read_text_file"}
    assert not kinds(service.events("u"), "error", "notification")


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
        ({"option_id": "allow", "extra": 1}, "extra: Extra inputs are not permitted"),
        ({"action": "accept"}, "action: Extra inputs are not permitted"),
        ({"option_id": 3}, "option_id: Input should be a valid string"),
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
    said = done["last_message"].removeprefix("permission: ")
    assert json.loads(said) == {"outcome": "selected", "optionId": "reject"}
    [resolved] = kinds(service.events("p"), "resolved")
    assert resolved["by"] == "client" and resolved["answer"] == {
        "outcome": "selected",
        "optionId": "reject",
    }


def test_a_question_needs_its_answer_in_form(service: Service) -> None:
    service.start_session("q", "question")
    service.wait_state("q", "waiting")
    url = "/v1/sessions/q/requests/q1"
    for body, error in (
        ({"action": "accept"}, "accept needs content"),
        (
            {"action": "maybe"},
            "action: Input should be 'accept', 'decline' or 'cancel'",
        ),
        ({"option_id": "allow"}, "option_id: Extra inputs are not permitted"),
        (
            {"action": "accept", "content": []},
            "content: Input should be a valid dictionary",
        ),
    ):
        with pytest.raises(ClientError, match=error):
            service.call("POST", url, body)
    service.call("POST", url, {"action": "accept", "content": {"colour": "red"}})
    said = service.wait_state("q", "idle")["last_message"].removeprefix("question: ")
    assert json.loads(said) == {"action": "accept", "content": {"colour": "red"}}


def test_a_declined_question(service: Service) -> None:
    service.start_session("d", "question")
    service.wait_state("d", "waiting")
    service.call("POST", "/v1/sessions/d/requests/q1", {"action": "decline"})
    said = service.wait_state("d", "idle")["last_message"].removeprefix("question: ")
    assert json.loads(said) == {"action": "decline"}


def test_the_agents_words_come_before_the_end_of_its_turn(service: Service) -> None:
    # The agent writes its text, then answers session/prompt: the SDK resolves the answer at once
    # and queues notifications, so the inbox must take them in the read loop, ahead of it.
    for n in range(5):
        name = f"o{n}"
        service.start_session(name, f"say word {n}")
        done = service.wait_state(name, "idle")
        assert done["last_message"] == f"word {n}"
        kinds_ = [e["kind"] for e in service.events(name)]
        last_update = max(i for i, k in enumerate(kinds_) if k == "update")
        assert last_update < kinds_.index("turn_end")
        assert service.call("GET", f"/v1/sessions/{name}/output?lines=2")["lines"] == [
            f"word {n}",
            "[turn ended: end_turn]",
        ]
