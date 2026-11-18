"""The API's bodies (README.md): what clients send, checked strictly, and what the runner answers.

Requests forbid unknown fields; `null` is the same as leaving an optional field out. The CLI reads
answers with the same types.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TypedDict

from .events import Delivery, Event, State
from .schema import JsonObject
from .store import Record

# --- Requests -----------------------------------------------------------------------------------


@dataclass(frozen=True, kw_only=True)
class StartRequest:
    """POST /v1/sessions."""

    name: str
    dir: str
    task: str | None = None
    agent: str | None = None
    model: str | None = None
    mode: str | None = None
    resume: str | None = None
    env: dict[str, str] | None = None
    origin: str | None = None
    session_meta: JsonObject | None = None


@dataclass(frozen=True, kw_only=True)
class SendRequest:
    """POST /v1/sessions/{name}/send."""

    text: str


@dataclass(frozen=True, kw_only=True)
class StopRequest:
    """POST /v1/sessions/{name}/stop."""

    reason: str | None = None


@dataclass(frozen=True, kw_only=True)
class EmptyRequest:
    """POST .../cancel and /v1/restart: no fields."""


# The answer to a request (POST /v1/sessions/{name}/requests/{id}) is parking.PermissionAnswer or
# parking.QuestionAnswer, depending on the request.

# --- Answers ------------------------------------------------------------------------------------


class PublicRecord(TypedDict):
    """A session's record as the API reports it: `env` gives the names only."""

    name: str
    agent: str
    dir: str
    created_at: float
    state: State
    reason: str | None
    model: str | None
    mode: str | None
    origin: str | None
    env: list[str]
    session_meta: JsonObject | None
    agent_session_id: str | None
    transcript: str | None
    title: str | None
    updated_at: float
    turns: int


def public(record: Record) -> PublicRecord:
    return PublicRecord(
        name=record.name,
        agent=record.agent,
        dir=record.dir,
        created_at=record.created_at,
        state=record.state,
        reason=record.reason,
        model=record.model,
        mode=record.mode,
        origin=record.origin,
        # Values may be secret-ish (tokens a caller passed).
        env=sorted(record.env),
        session_meta=record.session_meta,
        agent_session_id=record.agent_session_id,
        transcript=record.transcript,
        title=record.title,
        updated_at=record.updated_at,
        turns=record.turns,
    )


@dataclass(frozen=True, kw_only=True)
class SessionFields:
    name: str
    agent: str
    dir: str
    created_at: float
    state: State
    reason: str | None = None
    model: str | None = None
    mode: str | None = None
    origin: str | None = None
    env: list[str] = field(default_factory=list)
    session_meta: JsonObject | None = None
    agent_session_id: str | None = None
    transcript: str | None = None
    title: str | None = None
    updated_at: float = 0.0
    turns: int = 0


@dataclass(frozen=True, kw_only=True)
class SessionSummary(SessionFields):
    """A session in GET /v1/sessions."""

    pending: int
    alive: bool
    last_event_at: float


@dataclass(frozen=True, kw_only=True)
class SessionStatus(SessionFields):
    """GET /v1/sessions/{name}, and what most POSTs on a session return."""

    # The open permission requests and questions: each the event that announced it.
    pending: list[Event]
    queued: list[str]
    last_message: str
    alive: bool
    last_event_at: float


@dataclass(frozen=True)
class SessionList:
    sessions: list[SessionSummary]


@dataclass(frozen=True)
class AgentList:
    default: str
    agents: list[str]


@dataclass(frozen=True)
class Output:
    lines: list[str]


@dataclass(frozen=True)
class Sent:
    delivery: Delivery


@dataclass(frozen=True)
class Restarting:
    restarting: bool = True


@dataclass(frozen=True)
class ErrorBody:
    error: str
