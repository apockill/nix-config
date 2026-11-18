"""The API's bodies (README.md): what clients send, checked strictly, and what the runner answers.

Requests forbid unknown fields; `null` is the same as leaving an optional field out. The CLI reads
answers with the same models. The answer to a parked request is parking.PermissionAnswer or
parking.QuestionAnswer, depending on the request.
"""

from __future__ import annotations

from .base import JsonObject, Strict
from .events import Delivery, Event, State
from .store import Limit, Record

# --- Requests -----------------------------------------------------------------------------------


class StartRequest(Strict):
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
    # Whether the session's own processes may use this API; a session that may not can't start
    # one that may.
    allow_runner: bool | None = None


class SendRequest(Strict):
    """POST /v1/sessions/{name}/send."""

    text: str


class StopRequest(Strict):
    """POST /v1/sessions/{name}/stop."""

    reason: str | None = None


class EmptyRequest(Strict):
    """POST .../cancel: no fields."""


class RestartRequest(Strict):
    """POST /v1/restart: refused while a turn runs or a request waits, unless forced."""

    force: bool = False


# --- Answers ------------------------------------------------------------------------------------


class SessionFields(Strict):
    """A session's record as the API reports it: `env` gives the names only (values may be
    secret-ish, tokens a caller passed)."""

    name: str
    agent: str
    dir: str
    created_at: float
    state: State
    reason: str | None = None
    model: str | None = None
    mode: str | None = None
    origin: str | None = None
    env: list[str] = []
    session_meta: JsonObject | None = None
    agent_session_id: str | None = None
    transcript: str | None = None
    title: str | None = None
    updated_at: float = 0.0
    turns: int = 0
    queued: list[str] = []
    limit: Limit | None = None
    compact_window: int | None = None
    allow_runner: bool = False
    failed_turns: int = 0
    misfits: int = 0
    notify_error: str | None = None


def public(record: Record) -> dict[str, object]:
    """A record's fields for SessionFields (validated there)."""
    return {**record.model_dump(), "env": sorted(record.env)}


class SessionSummary(SessionFields):
    """A session in GET /v1/sessions."""

    pending: int
    alive: bool
    last_event_at: float


class SessionStatus(SessionFields):
    """GET /v1/sessions/{name}, and what most POSTs on a session return."""

    # The open permission requests and questions: each the event that announced it.
    pending: list[Event]
    last_message: str
    alive: bool
    last_event_at: float


class SessionList(Strict):
    sessions: list[SessionSummary]


class AgentList(Strict):
    default: str
    agents: list[str]


class Output(Strict):
    lines: list[str]


class Sent(Strict):
    delivery: Delivery


class Restarting(Strict):
    restarting: bool = True


class ErrorBody(Strict):
    error: str
    # With a 429: when the usage limit resets (Unix seconds), if the agent said.
    resets_at: float | None = None
