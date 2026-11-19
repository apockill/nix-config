"""A session's events as text: what `output` (and so `agent peek`) shows."""

from __future__ import annotations

from collections.abc import Iterable

from acp.schema import (
    AgentMessageChunk,
    AgentPlanUpdate,
    TextContentBlock,
    ToolCallProgress,
    ToolCallStart,
)

from .base import JsonObject
from .events import (
    Event,
    Failed,
    PermissionAsked,
    Prompted,
    QuestionAsked,
    StateChanged,
    TurnEnded,
    Updated,
)


def render(events: Iterable[Event]) -> list[str]:
    """What was asked, what the agent said, its tool calls and requests, and how turns ended."""
    lines: list[str] = []
    text = ""  # the agent message being streamed

    def flush() -> None:
        nonlocal text
        if text.strip():
            lines.extend(text.strip("\n").splitlines())
        text = ""

    for event in events:
        body = event.body
        if isinstance(body, Updated):
            update = body.parsed()
            if isinstance(update, AgentMessageChunk):
                if isinstance(update.content, TextContentBlock):
                    text += update.content.text
            elif isinstance(update, ToolCallStart):
                flush()
                lines.append(f"[tool] {update.title or update.kind or '?'}")
            elif isinstance(update, ToolCallProgress) and update.status == "failed":
                flush()
                lines.append(f"[tool failed] {update.title or update.tool_call_id}")
            elif isinstance(update, AgentPlanUpdate):
                flush()
                lines.extend(f"[plan {e.status}] {e.content}" for e in update.entries)
            continue
        flush()
        match body:
            case Prompted():
                lines.append(f"> {body.text}".replace("\n", " "))
            case PermissionAsked():
                options = ", ".join(o.option_id for o in body.options)
                lines.append(f"[permission {body.request_id}] {body.title} ({options})")
            case QuestionAsked():
                lines.append(f"[question {body.request_id}] {body.message}")
                lines.extend(question_fields(body.schema_))
            case TurnEnded():
                lines.append(f"[turn ended: {body.stop_reason}]")
            case Failed():
                lines.append(f"[error] {body.message}")
            case StateChanged() if body.state in ("failed", "offline", "stopped"):
                lines.append(f"[{body.state}] {body.reason or ''}".rstrip())
    flush()
    return lines


def question_fields(schema: JsonObject | None) -> list[str]:
    """A form's fields, one line each, with their choices (`enum`, or `oneOf`/`anyOf` consts)."""
    properties = schema.get("properties") if schema else None
    if not isinstance(properties, dict):
        return []
    lines = []
    for prop, spec in properties.items():
        if not isinstance(spec, dict):
            continue
        label = spec.get("title") or spec.get("description") or ""
        choices = spec.get("enum")
        if not isinstance(choices, list) or not choices:
            alternatives = spec.get("oneOf") or spec.get("anyOf")
            choices = (
                [o.get("const") for o in alternatives if isinstance(o, dict)]
                if isinstance(alternatives, list)
                else []
            )
        shown = [str(c) for c in choices if c is not None]
        lines.append(
            f"  {prop}: {label}" + (f" [{' | '.join(shown)}]" if shown else "")
        )
    return lines


def asked(event: Event) -> tuple[str, str]:
    """A parked request's id and what it asks: a permission's title, a question's message."""
    body = event.body
    if isinstance(body, PermissionAsked):
        return body.request_id, str(body.title)
    if isinstance(body, QuestionAsked):
        return body.request_id, str(body.message)
    raise ValueError(f"a {event.kind} event isn't a request")
