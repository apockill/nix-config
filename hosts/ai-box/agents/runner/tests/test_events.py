"""Tests for events.py: the flat wire form of every kind, and logs from before the split."""

from __future__ import annotations

import json
import typing

import pytest
from acp.schema import (
    AcceptElicitationResponse,
    AllowedOutcome,
    PermissionOption,
)
from agent_runner.base import JsonObject
from agent_runner.events import (
    AgentNotification,
    Body,
    Cancelled,
    Event,
    Failed,
    Heartbeat,
    Notified,
    PermissionAsked,
    Prompted,
    QuestionAsked,
    Resolved,
    SessionOpened,
    StateChanged,
    TurnEnded,
    Updated,
    acp_json,
    decode_streamed,
)
from pydantic import ValidationError

# Lines as the runner wrote them before the split into modules (runner.py's emit).
PRE_SPLIT = [
    '{"seq": 1, "ts": 1795000000.0, "session": "job", "kind": "state", "state": "starting", "reason": null}',
    '{"seq": 2, "ts": 1795000001.5, "session": "job", "kind": "session", "agent_session_id": "9c32", "transcript": "/t/x.jsonl", "agent_info": {"name": "fake", "version": "0"}}',
    '{"seq": 3, "ts": 1795000002.0, "session": "job", "kind": "prompt", "text": "hello", "delivery": "sent"}',
    '{"seq": 4, "ts": 1795000002.1, "session": "job", "kind": "update", "update": {"sessionUpdate": "agent_message_chunk", "content": {"type": "text", "text": "hi"}}}',
    '{"seq": 5, "ts": 1795000002.2, "session": "job", "kind": "permission", "request_id": "p1", "title": "touch x", "tool_call_id": "t1", "options": [{"optionId": "allow", "name": "Allow", "kind": "allow_once"}]}',
    '{"seq": 6, "ts": 1795000002.3, "session": "job", "kind": "resolved", "request_id": "p1", "by": "client", "answer": {"outcome": "selected", "optionId": "allow"}}',
    '{"seq": 7, "ts": 1795000002.4, "session": "job", "kind": "question", "request_id": "q2", "message": "Which?", "mode": "form", "schema": {"type": "object"}, "url": null}',
    '{"seq": 8, "ts": 1795000002.5, "session": "job", "kind": "resolved", "request_id": "q2", "by": "client", "answer": {"action": "accept", "content": {"c": "red"}}}',
    '{"seq": 9, "ts": 1795000002.6, "session": "job", "kind": "resolved", "request_id": "p3", "by": "agent", "answer": null}',
    '{"seq": 10, "ts": 1795000002.7, "session": "job", "kind": "resolved", "request_id": "p4", "by": "runner", "answer": null, "reason": "stopped"}',
    '{"seq": 11, "ts": 1795000002.8, "session": "job", "kind": "turn_end", "stop_reason": "end_turn"}',
    '{"seq": 12, "ts": 1795000002.9, "session": "job", "kind": "cancel"}',
    '{"seq": 13, "ts": 1795000003.0, "session": "job", "kind": "error", "message": "boom"}',
    '{"seq": 14, "ts": 1795000003.1, "session": "job", "kind": "notified", "message": "m", "ok": false, "error": "exit 1: x"}',
    '{"seq": 15, "ts": 1795000003.2, "session": "job", "kind": "notification", "method": "auth/status_update", "params": {"ok": true}}',
]


# The kinds whose lines hold an ACP object of the SDK's, which writes its keys in its own order.
SDK_ORDER = {"permission", "resolved"}

KINDS = {
    typing.get_args(cls.model_fields["kind"].annotation)[0]
    for cls in typing.get_args(typing.get_args(Body)[0])
}


@pytest.mark.parametrize("line", PRE_SPLIT)
def test_lines_from_before_the_split_read_and_write_back_the_same(line: str) -> None:
    event = Event.model_validate_json(line)
    again = json.dumps(event.model_dump(mode="json"), ensure_ascii=False)
    assert json.loads(again) == json.loads(line)
    if event.kind not in SDK_ORDER:
        assert again == line


def test_every_kind_is_covered_by_the_pre_split_lines() -> None:
    kinds = {json.loads(line)["kind"] for line in PRE_SPLIT}
    assert kinds == KINDS


def test_the_bodies_decode_to_their_types() -> None:
    events = [Event.model_validate_json(line) for line in PRE_SPLIT]
    bodies: list[Body] = [e.body for e in events]
    assert bodies[0] == StateChanged(state="starting")
    assert bodies[1] == SessionOpened(
        agent_session_id="9c32",
        transcript="/t/x.jsonl",
        agent_info={"name": "fake", "version": "0"},
    )
    assert bodies[2] == Prompted(text="hello", delivery="sent")
    assert isinstance(bodies[3], Updated)
    assert bodies[4] == PermissionAsked(
        request_id="p1",
        title="touch x",
        tool_call_id="t1",
        options=[PermissionOption(option_id="allow", name="Allow", kind="allow_once")],
    )
    assert bodies[5] == Resolved(
        request_id="p1",
        by="client",
        answer=AllowedOutcome(outcome="selected", option_id="allow"),
    )
    assert isinstance(bodies[6], QuestionAsked)
    assert bodies[6].schema_ == {"type": "object"}
    assert bodies[7] == Resolved(
        request_id="q2",
        by="client",
        answer=AcceptElicitationResponse(action="accept", content={"c": "red"}),
    )
    assert bodies[9] == Resolved(request_id="p4", by="runner", reason="stopped")
    assert bodies[10] == TurnEnded(stop_reason="end_turn")
    assert bodies[11] == Cancelled()
    assert bodies[12] == Failed(message="boom")
    assert bodies[13] == Notified(message="m", ok=False, error="exit 1: x")
    assert bodies[14] == AgentNotification(
        method="auth/status_update", params={"ok": True}
    )
    assert events[3].kind == "update" and events[3].seq == 4


def test_the_envelope_comes_first() -> None:
    event = Event(seq=7, ts=1.5, session="s", body=StateChanged(state="idle"))
    assert list(event.model_dump(mode="json")) == [
        "seq",
        "ts",
        "session",
        "kind",
        "state",
        "reason",
    ]


def test_resolved_gives_its_reason_only_when_the_runner_dropped_it() -> None:
    by_client = Resolved(request_id="p1", by="client")
    assert "reason" not in by_client.model_dump(mode="json")
    dropped = Resolved(request_id="p1", by="runner", reason="stopped")
    assert dropped.model_dump(mode="json")["reason"] == "stopped"


def test_acp_objects_go_out_as_acp_json() -> None:
    option = PermissionOption(option_id="a", name="A", kind="allow_once")
    assert acp_json(option) == {"optionId": "a", "name": "A", "kind": "allow_once"}
    asked = PermissionAsked(request_id="p1", options=[option])
    assert asked.model_dump(mode="json")["options"] == [acp_json(option)]


def test_an_update_reads_as_the_sdk_model_of_its_kind() -> None:
    chunk = Updated(
        update={
            "sessionUpdate": "agent_message_chunk",
            "content": {"type": "text", "text": "hi"},
        }
    )
    assert type(chunk.parsed()).__name__ == "AgentMessageChunk"
    assert Updated(update={"sessionUpdate": "a_kind_from_the_future"}).parsed() is None
    assert (
        Updated(update={"sessionUpdate": "tool_call"}).parsed() is None
    )  # no toolCallId


@pytest.mark.parametrize(
    "data",
    [
        [1],
        {"seq": 1, "ts": 0, "session": "s", "kind": "nope"},
        {"ts": 0, "session": "s", "kind": "cancel"},
        {"seq": 1, "ts": 0, "session": "s", "kind": "state"},
        {"seq": 1, "ts": 0, "session": "s", "kind": "state", "state": "gone"},
        {"seq": 1, "ts": 0, "session": "s", "kind": "cancel", "x": 1},
        {"seq": "1", "ts": 0, "session": "s", "kind": "cancel"},
    ],
)
def test_events_that_do_not_fit(data: object) -> None:
    with pytest.raises(ValidationError):
        Event.model_validate(data)


def test_heartbeats() -> None:
    beat = Heartbeat(ts=2.0, seq=5)
    assert beat.model_dump(mode="json") == {"kind": "heartbeat", "ts": 2.0, "seq": 5}
    assert decode_streamed({"kind": "heartbeat", "ts": 2, "seq": 5}) == beat
    streamed = decode_streamed(json.loads(PRE_SPLIT[0]))
    assert isinstance(streamed, Event) and streamed.seq == 1


def test_an_error_event_carries_the_agents_kind_and_data_only_when_given() -> None:
    plain = Event(seq=1, ts=1.0, session="s", body=Failed(message="boom"))
    assert plain.model_dump(mode="json") == {
        "seq": 1,
        "ts": 1.0,
        "session": "s",
        "kind": "error",
        "message": "boom",
    }
    data: JsonObject = {
        "errorKind": "rate_limit",
        "rateLimit": {"resetsAt": 1795010400},
    }
    limited = Failed(message="the turn failed", error_kind="rate_limit", data=data)
    flat = Event(seq=2, ts=2.0, session="s", body=limited).model_dump(mode="json")
    assert flat["error_kind"] == "rate_limit" and flat["data"] == data
    assert Event.model_validate(flat).body == limited
