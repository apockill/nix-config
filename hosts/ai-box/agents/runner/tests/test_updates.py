"""Tests for updates.py: the session updates the runner reads."""

from __future__ import annotations

from agent_runner.schema import JsonObject, JsonValue
from agent_runner.updates import (
    AgentMessageChunk,
    Plan,
    ToolCall,
    ToolCallUpdate,
    message_text,
    session_title,
    view,
)


def chunk(text: JsonValue, type_: str = "text") -> JsonObject:
    return {
        "sessionUpdate": "agent_message_chunk",
        "content": {"type": type_, "text": text},
    }


def test_the_agents_text() -> None:
    assert message_text(chunk("hi")) == "hi"
    assert message_text(chunk("x", "image")) == ""
    thought: JsonObject = {
        "sessionUpdate": "agent_thought_chunk",
        "content": {"type": "text"},
    }
    assert message_text(thought) == ""


def test_the_title() -> None:
    assert session_title({"sessionUpdate": "session_info_update", "title": "T"}) == "T"
    assert session_title({"sessionUpdate": "session_info_update"}) is None
    assert session_title({"sessionUpdate": "session_info_update", "title": ""}) is None
    assert session_title({"sessionUpdate": "plan", "title": "T"}) is None


def test_views() -> None:
    assert isinstance(view(chunk("x")), AgentMessageChunk)
    call = view({"sessionUpdate": "tool_call", "title": "ls", "toolCallId": "t"})
    assert call == ToolCall(title="ls")
    upd = view(
        {"sessionUpdate": "tool_call_update", "toolCallId": "t", "status": "failed"}
    )
    assert upd == ToolCallUpdate(tool_call_id="t", status="failed")
    plan = view(
        {"sessionUpdate": "plan", "entries": [{"content": "a", "priority": "high"}]}
    )
    assert isinstance(plan, Plan) and plan.entries[0].status == "?"


def test_others_and_malformed_ones_have_no_view() -> None:
    assert view({"sessionUpdate": "usage_update", "used": 1}) is None
    assert view({}) is None
    assert view({"sessionUpdate": 3}) is None
    assert view({"sessionUpdate": "tool_call", "title": 3}) is None
    assert message_text(chunk(5)) == ""
