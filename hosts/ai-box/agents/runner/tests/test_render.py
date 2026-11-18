"""Tests for render.py, beyond test_e2e.py's test_render: requests, plans, states, `asked`."""

from __future__ import annotations

import pytest
from agent_runner.acp import PermissionOption
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
from agent_runner.schema import JsonValue


def ev(body: Body) -> Event:
    return Event(1, 0.0, "s", body)


PERMISSION = PermissionAsked(
    request_id="p1",
    title="touch x",
    options=[
        PermissionOption("allow", "Allow", "allow_once"),
        PermissionOption("reject", "Reject", "reject_once"),
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
                        {"content": "read", "status": "completed"},
                        {"content": "write"},
                    ],
                }
            )
        ),
        ev(Updated(update={"sessionUpdate": "tool_call", "kind": "read"})),
        ev(Updated(update={"sessionUpdate": "tool_call"})),
        ev(
            Updated(update={"sessionUpdate": "tool_call_update", "status": "completed"})
        ),
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
        "[plan ?] write",
        "[tool] read",
        "[tool] ?",
        "[offline] the runner restarted",
        "[stopped]",
        "[turn ended: None]",
    ]


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
def test_question_fields(schema: JsonValue, lines: list[str]) -> None:
    assert question_fields(schema) == lines


def test_asked() -> None:
    assert asked(ev(PERMISSION)) == ("p1", "touch x")
    assert asked(ev(QuestionAsked(request_id="q2", message="Which?"))) == (
        "q2",
        "Which?",
    )
    with pytest.raises(ValueError, match="isn't a request"):
        asked(ev(Cancelled()))
