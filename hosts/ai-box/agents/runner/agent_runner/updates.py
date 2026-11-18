"""The few ACP session updates the runner looks into, as typed views of the update's JSON.

Updates are passed on to clients unchanged (the `update` event); the runner reads only the agent's
text (a session's `last_message`), its title for the conversation, and what `peek` shows.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .schema import JsonObject, Open, SchemaError, alias, decode


@dataclass(frozen=True)
class Content(Open):
    type: str
    text: str | None = None


@dataclass(frozen=True)
class AgentMessageChunk(Open):
    content: Content


@dataclass(frozen=True)
class SessionInfo(Open):
    title: str | None = None


@dataclass(frozen=True)
class ToolCall(Open):
    title: str | None = None
    kind: str | None = None


@dataclass(frozen=True)
class ToolCallUpdate(Open):
    tool_call_id: str | None = field(default=None, metadata=alias("toolCallId"))
    title: str | None = None
    status: str | None = None


@dataclass(frozen=True)
class PlanEntry(Open):
    content: str = ""
    status: str = "?"


@dataclass(frozen=True)
class Plan(Open):
    entries: list[PlanEntry] = field(default_factory=list)


View = AgentMessageChunk | SessionInfo | ToolCall | ToolCallUpdate | Plan

VIEWS: dict[str, type[View]] = {
    "agent_message_chunk": AgentMessageChunk,
    "session_info_update": SessionInfo,
    "tool_call": ToolCall,
    "tool_call_update": ToolCallUpdate,
    "plan": Plan,
}


def view(update: JsonObject) -> View | None:
    """The update as one of the views above; None for the others, or one that doesn't fit."""
    kind = update.get("sessionUpdate")
    cls = VIEWS.get(kind) if isinstance(kind, str) else None
    if cls is None:
        return None
    try:
        return decode(cls, update)
    except SchemaError:
        return None


def message_text(update: JsonObject) -> str:
    """The agent's text in this update ("" unless it's a text chunk of the agent's message)."""
    v = view(update)
    if isinstance(v, AgentMessageChunk) and v.content.type == "text":
        return v.content.text or ""
    return ""


def session_title(update: JsonObject) -> str | None:
    """The agent's new title for the conversation, if this update gives one."""
    v = view(update)
    return v.title if isinstance(v, SessionInfo) and v.title else None
