"""api_types.py: the API's bodies, decoded strictly, and the record as the API reports it."""

from __future__ import annotations

import pytest
from agent_runner.acp import PermissionOption
from agent_runner.api_types import (
    AgentList,
    EmptyRequest,
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
from agent_runner.schema import SchemaError, decode, encode
from agent_runner.store import Record


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


def test_start_request_is_strict() -> None:
    req = decode(
        StartRequest,
        {"name": "a", "dir": "/w", "resume": None, "env": {"X": "1"}, "mode": None},
    )
    assert req.resume is None and req.env == {"X": "1"} and req.task is None
    with pytest.raises(SchemaError, match="bogus: unknown field"):
        decode(StartRequest, {"name": "a", "dir": "/w", "bogus": 1})
    with pytest.raises(SchemaError, match="dir: missing"):
        decode(StartRequest, {"name": "a"})
    with pytest.raises(SchemaError, match="name: must be a string"):
        decode(StartRequest, {"name": 3, "dir": "/w"})
    with pytest.raises(SchemaError, match="env.X: must be a string"):
        decode(StartRequest, {"name": "a", "dir": "/w", "env": {"X": 1}})
    with pytest.raises(SchemaError, match="session_meta: must be an object"):
        decode(StartRequest, {"name": "a", "dir": "/w", "session_meta": []})


def test_small_requests() -> None:
    assert decode(SendRequest, {"text": "hi"}).text == "hi"
    with pytest.raises(SchemaError, match="text: missing"):
        decode(SendRequest, {})
    assert decode(StopRequest, {}).reason is None
    assert decode(StopRequest, {"reason": None}).reason is None
    decode(EmptyRequest, {})
    with pytest.raises(SchemaError, match="x: unknown field"):
        decode(EmptyRequest, {"x": 1})


def test_status_round_trips_with_its_pending_events() -> None:
    asked = PermissionAsked(
        request_id="p1",
        title="touch x",
        tool_call_id="t1",
        options=[PermissionOption("allow", "Allow", "allow_once")],
    )
    status = SessionStatus(
        **public(record()),
        pending=[Event(5, 2.0, "job", asked)],
        queued=["next"],
        last_message="hi",
        alive=True,
        last_event_at=2.0,
    )
    data = encode(status)
    assert isinstance(data, dict)
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
    assert list(data)[-5:] == [
        "pending",
        "queued",
        "last_message",
        "alive",
        "last_event_at",
    ]
    assert decode(SessionStatus, data) == status


def test_lists_and_small_answers() -> None:
    summary = SessionSummary(
        **public(record()), pending=0, alive=False, last_event_at=0.0
    )
    data = encode(SessionList([summary]))
    assert decode(SessionList, data) == SessionList([summary])
    assert encode(AgentList("claude", ["antigravity", "claude"])) == {
        "default": "claude",
        "agents": ["antigravity", "claude"],
    }
    assert decode(Sent, {"delivery": "steered"}).delivery == "steered"
    with pytest.raises(SchemaError, match="delivery: must be one of"):
        decode(Sent, {"delivery": "posted"})
