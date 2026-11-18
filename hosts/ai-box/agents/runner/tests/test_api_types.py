"""api_types.py: the API's bodies, validated strictly, and the record as the API reports it."""

from __future__ import annotations

from typing import Any

import pytest
from acp.schema import PermissionOption
from agent_runner.api_types import (
    AgentList,
    EmptyRequest,
    ErrorBody,
    Output,
    Restarting,
    SendRequest,
    Sent,
    SessionList,
    SessionStatus,
    SessionSummary,
    StartRequest,
    StopRequest,
    public,
)
from agent_runner.events import Event, PermissionAsked
from agent_runner.store import Record
from pydantic import ValidationError


def record() -> Record:
    return Record(
        name="job",
        agent="claude",
        dir="/w",
        created_at=1.0,
        state="idle",
        env={"TOKEN": "secret", "A": "1"},
        session_meta={"claudeCode": {}},
        agent_session_id="sid",
        turns=2,
    )


def test_public_reports_env_names_only() -> None:
    out = public(record())
    assert out["env"] == ["A", "TOKEN"]
    assert "secret" not in str(out)
    assert out["agent_session_id"] == "sid" and out["turns"] == 2
    assert list(out) == [
        "name",
        "agent",
        "dir",
        "created_at",
        "state",
        "reason",
        "model",
        "mode",
        "origin",
        "env",
        "session_meta",
        "agent_session_id",
        "transcript",
        "title",
        "updated_at",
        "turns",
    ]


def refused(model: type[Any], data: dict[str, Any], error: str) -> None:
    with pytest.raises(ValidationError) as e:
        model.model_validate(data)
    assert error in str(e.value), str(e.value)


def test_start_request_is_strict() -> None:
    req = StartRequest.model_validate(
        {"name": "a", "dir": "/w", "resume": None, "env": {"X": "1"}, "mode": None}
    )
    assert req.resume is None and req.env == {"X": "1"} and req.task is None
    refused(
        StartRequest,
        {"name": "a", "dir": "/w", "bogus": 1},
        "Extra inputs are not permitted",
    )
    refused(StartRequest, {"name": "a"}, "dir\n  Field required")
    refused(StartRequest, {"name": 3, "dir": "/w"}, "Input should be a valid string")
    refused(StartRequest, {"name": "a", "dir": "/w", "env": {"X": 1}}, "env.X\n")
    refused(
        StartRequest,
        {"name": "a", "dir": "/w", "session_meta": []},
        "session_meta\n  Input should be a valid dictionary",
    )
    # Strict: no coercion of one type into another.
    refused(StartRequest, {"name": "a", "dir": "/w", "task": 5}, "task\n")


def test_small_requests() -> None:
    assert SendRequest.model_validate({"text": "hi"}).text == "hi"
    refused(SendRequest, {}, "text\n  Field required")
    assert StopRequest.model_validate({}).reason is None
    assert StopRequest.model_validate({"reason": None}).reason is None
    EmptyRequest.model_validate({})
    refused(EmptyRequest, {"x": 1}, "x\n  Extra inputs are not permitted")


def status() -> SessionStatus:
    asked = PermissionAsked(
        request_id="p1",
        title="touch x",
        tool_call_id="t1",
        options=[PermissionOption(option_id="allow", name="Allow", kind="allow_once")],
    )
    return SessionStatus.model_validate(
        {
            **public(record()),
            "pending": [Event(seq=5, ts=2.0, session="job", body=asked)],
            "queued": ["next"],
            "last_message": "hi",
            "alive": True,
            "last_event_at": 2.0,
        }
    )


def test_status_round_trips_with_its_pending_events() -> None:
    data = status().model_dump(mode="json")
    assert data["pending"] == [
        {
            "seq": 5,
            "ts": 2.0,
            "session": "job",
            "kind": "permission",
            "request_id": "p1",
            "title": "touch x",
            "tool_call_id": "t1",
            "options": [{"optionId": "allow", "name": "Allow", "kind": "allow_once"}],
        }
    ]
    assert data["env"] == ["A", "TOKEN"]
    assert list(data)[-5:] == [
        "pending",
        "queued",
        "last_message",
        "alive",
        "last_event_at",
    ]
    assert SessionStatus.model_validate(data) == status()


def test_lists_and_small_answers() -> None:
    summary = SessionSummary.model_validate(
        {**public(record()), "pending": 0, "alive": False, "last_event_at": 0.0}
    )
    data = SessionList(sessions=[summary]).model_dump(mode="json")
    assert SessionList.model_validate(data) == SessionList(sessions=[summary])
    assert AgentList(
        default="claude", agents=["antigravity", "claude"]
    ).model_dump() == {
        "default": "claude",
        "agents": ["antigravity", "claude"],
    }
    assert Sent.model_validate({"delivery": "steered"}).delivery == "steered"
    refused(
        Sent, {"delivery": "posted"}, "Input should be 'sent', 'steered' or 'queued'"
    )
    assert Restarting().model_dump() == {"restarting": True}
    assert Output(lines=["a"]).model_dump() == {"lines": ["a"]}
    assert ErrorBody(error="x").model_dump() == {"error": "x"}


def test_answers_refuse_what_they_dont_know() -> None:
    data = status().model_dump(mode="json")
    refused(
        SessionStatus, {**data, "extra": 1}, "extra\n  Extra inputs are not permitted"
    )
    refused(SessionStatus, {**data, "state": "sleeping"}, "state\n")
