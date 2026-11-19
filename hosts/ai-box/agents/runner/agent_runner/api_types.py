"""The API's bodies: what clients send, checked strictly, and what the runner answers.

The API is HTTP/1.1 on the runner's unix socket, one request per connection, JSON bodies (the
transport and who may call: README.md), e.g. `curl --unix-socket <socket>
http://runner/v1/sessions` (the host is ignored). The routes (api.py):

  GET  /v1/agents                               AgentList
  GET  /v1/sessions                             SessionList, oldest first
  POST /v1/sessions                             StartRequest -> 201 SessionStatus
  GET  /v1/sessions/{name}                      SessionStatus
  GET  /v1/sessions/{name}/output?lines=40      Output: what `agent peek` prints
  POST /v1/sessions/{name}/send                 SendRequest -> Sent
  POST /v1/sessions/{name}/cancel               EmptyRequest -> SessionStatus
  POST /v1/sessions/{name}/stop                 StopRequest -> SessionStatus
  POST /v1/sessions/{name}/requests/{id}        parking.PermissionAnswer (p1, ...) or
                                                parking.QuestionAnswer (q1, ...) -> SessionStatus
  GET  /v1/sessions/{name}/events?since=&follow=1   NDJSON events (events.py): the stored ones
  GET  /v1/events?since=&follow=1                   after `since`, then with follow the live ones
                                                    and a heartbeat every 15 s; /v1/events keeps
                                                    the last 20,000 of all sessions
  POST /v1/restart                              RestartRequest -> Restarting
  GET  /v1/openapi.json                         the OpenAPI schema of all of these

Requests forbid unknown fields; `null` is the same as leaving an optional field out. The CLI reads
answers with the same models. An error is ErrorBody with its status:
  400  a bad request (the message names the field), a body that isn't JSON
  403  the caller is inside a session that may not use the runner (peers.py)
  404  no such session, request or path
  409  the session's state doesn't allow it (send to a stopped one, start over a live one,
       restart while turns run)
  429  the account's usage limit: `resets_at` when the agent said
  502  the agent failed (couldn't start, sign-in missing or expired, died): the session is failed
  504  the agent didn't answer a setup request in time
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
    # The vendor's own transcript, written live by the agent: the complete record (the events
    # are the live channel). Claude: ~/.claude/projects/<folder>/<id>.jsonl, subagents in
    # <id>/subagents/; Antigravity: ~/.gemini/antigravity-cli/brain/<id>/.system_generated/logs/
    # transcript.jsonl, subagents in their own brain/<sub-id>/.
    transcript: str | None = None
    # The agent's own title for the conversation, once it has one.
    title: str | None = None
    updated_at: float = 0.0
    turns: int = 0
    queued: list[str] = []
    limit: Limit | None = None
    # Null: the agent's own default.
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
    # Whether the agent's process is up. With `state`, last_event_at tells a session that works
    # (running, or idle with recent events: agy finishing subagent work) from one gone quiet.
    alive: bool
    last_event_at: float


class SessionStatus(SessionFields):
    """GET /v1/sessions/{name}, and what most POSTs on a session return."""

    # The open permission requests and questions: each the event that announced it.
    pending: list[Event]
    # The agent's text since the last prompt.
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
