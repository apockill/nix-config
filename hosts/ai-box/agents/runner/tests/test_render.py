"""Tests for render.py, beyond test_e2e.py's test_render: requests, plans, states, `asked`."""

from __future__ import annotations

from typing import Any

import pytest
from acp.schema import PermissionOption
from agent_runner.base import JsonObject
from agent_runner.events import (
    Body,
    Cancelled,
    Event,
    PermissionAsked,
    QuestionAsked,
    StateChanged,
    TurnEnded,
    Updated,
)
from agent_runner.render import asked, question_fields, render


def ev(body: Body) -> Event:
    return Event(seq=1, ts=0.0, session="s", body=body)


def tool(update: str, **fields: Any) -> Updated:
    return Updated(update={"sessionUpdate": update, "toolCallId": "t1", **fields})


PERMISSION = PermissionAsked(
    request_id="p1",
    title="touch x",
    options=[
        PermissionOption(option_id="allow", name="Allow", kind="allow_once"),
        PermissionOption(option_id="reject", name="Reject", kind="reject_once"),
    ],
)


def test_requests_plans_and_states() -> None:
    events = [
        ev(PERMISSION),
        ev(
            Updated(
                update={
                    "sessionUpdate": "plan",
                    "entries": [
                        {"content": "read", "status": "completed", "priority": "high"},
                        {"content": "write", "status": "pending", "priority": "low"},
                    ],
                }
            )
        ),
        ev(tool("tool_call", title="", kind="read")),
        ev(tool("tool_call", title="")),
        ev(tool("tool_call_update", status="completed")),
        ev(tool("tool_call_update", status="failed", title="rm y")),
        ev(tool("tool_call_update", status="failed")),
        # Not ACP (no toolCallId): passed on to clients, but nothing to show.
        ev(Updated(update={"sessionUpdate": "tool_call", "title": "no id"})),
        ev(Updated(update={"sessionUpdate": "a_kind_from_the_future"})),
        ev(Updated(update={"sessionUpdate": "usage_update", "used": 3})),
        ev(StateChanged(state="idle")),
        ev(StateChanged(state="offline", reason="the runner restarted")),
        ev(StateChanged(state="stopped")),
        ev(Cancelled()),
        ev(TurnEnded(stop_reason=None)),
    ]
    assert render(events) == [
        "[permission p1] touch x (allow, reject)",
        "[plan completed] read",
        "[plan pending] write",
        "[tool] read",
        "[tool] ?",
        "[tool failed] rm y",
        "[tool failed] t1",
        "[offline] the runner restarted",
        "[stopped]",
        "[turn ended: None]",
    ]


def test_only_text_content_is_text() -> None:
    image: JsonObject = {"type": "image", "data": "AAAA", "mimeType": "image/png"}
    events = [
        ev(Updated(update={"sessionUpdate": "agent_message_chunk", "content": image})),
        ev(TurnEnded(stop_reason="end_turn")),
    ]
    assert render(events) == ["[turn ended: end_turn]"]


def test_text_is_joined_until_something_else_comes() -> None:
    def chunk(text: str, kind: str = "agent_message_chunk") -> Event:
        return ev(
            Updated(
                update={
                    "sessionUpdate": kind,
                    "content": {"type": "text", "text": text},
                }
            )
        )

    events = [
        chunk("a"),
        chunk("thinking", "agent_thought_chunk"),
        chunk("b\n\n"),
        ev(StateChanged(state="idle")),
        chunk("  "),
        ev(TurnEnded(stop_reason="end_turn")),
    ]
    assert render(events) == ["ab", "[turn ended: end_turn]"]


@pytest.mark.parametrize(
    "schema, lines",
    [
        (None, []),
        ({"properties": []}, []),
        (
            {
                "properties": {
                    "a": {"description": "Pick", "enum": ["x", "y"]},
                    "b": {"title": "B", "anyOf": [{"const": 1}, {"title": "no const"}]},
                    "c": {"enum": [], "oneOf": [{"const": "z"}]},
                    "d": {"type": "string"},
                    "e": "not a field",
                }
            },
            ["  a: Pick [x | y]", "  b: B [1]", "  c:  [z]", "  d: "],
        ),
    ],
)
def test_question_fields(schema: JsonObject | None, lines: list[str]) -> None:
    assert question_fields(schema) == lines


def test_asked() -> None:
    assert asked(ev(PERMISSION)) == ("p1", "touch x")
    assert asked(ev(QuestionAsked(request_id="q2", message="Which?"))) == (
        "q2",
        "Which?",
    )
    with pytest.raises(ValueError, match="isn't a request"):
        asked(ev(Cancelled()))
