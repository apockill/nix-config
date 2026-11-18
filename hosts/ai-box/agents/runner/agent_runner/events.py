"""A session's events: what the event log stores and the API streams (README.md, "Events").

An `Event` is the envelope (`seq`, increasing across all sessions; `ts`; `session`) and a body
whose `kind` says which. On the wire the two are one flat object:
`{"seq": 1, "ts": ..., "session": "job", "kind": "state", "state": "idle", "reason": null}`.
"""

from __future__ import annotations

from typing import Annotated, Any, Literal

from acp.schema import (
    AcceptElicitationResponse,
    AllowedOutcome,
    CancelElicitationResponse,
    DeclineElicitationResponse,
    DeniedOutcome,
    PermissionOption,
    SessionNotification,
)
from pydantic import (
    BaseModel,
    Field,
    SerializerFunctionWrapHandler,
    ValidationError,
    field_serializer,
    model_serializer,
    model_validator,
)

from .base import JsonObject, JsonValue, Strict

# Session states (README.md, "States").
State = Literal[
    "starting",
    "running",
    "idle",
    "waiting",
    "limited",
    "offline",
    "failed",
    "stopped",
]
ENDED: frozenset[State] = frozenset({"failed", "stopped"})

# How `send` handed a message to the agent.
Delivery = Literal["sent", "steered", "queued"]

# What went back to the agent for a permission (outcome) or a question (action).
Answer = (
    AllowedOutcome
    | DeniedOutcome
    | AcceptElicitationResponse
    | DeclineElicitationResponse
    | CancelElicitationResponse
)


def acp_json(model: BaseModel) -> JsonObject:
    """An SDK model as ACP's JSON: camelCase, nothing left at its default None."""
    return model.model_dump(mode="json", by_alias=True, exclude_none=True)


class StateChanged(Strict):
    kind: Literal["state"] = "state"
    state: State
    reason: str | None = None


class SessionOpened(Strict):
    """The agent's session was created or resumed."""

    kind: Literal["session"] = "session"
    agent_session_id: str
    transcript: str | None = None
    agent_info: JsonObject | None = None


class Prompted(Strict):
    kind: Literal["prompt"] = "prompt"
    text: str
    delivery: Delivery


class Updated(Strict):
    """An ACP session/update, as the agent sent it."""

    kind: Literal["update"] = "update"
    update: JsonObject

    def parsed(self) -> BaseModel | None:
        """The update as the SDK's model of its kind; None for a kind (or shape) it doesn't know."""
        try:
            return SessionNotification.model_validate(
                {"sessionId": "-", "update": self.update}
            ).update
        except ValidationError:
            return None


class TurnEnded(Strict):
    kind: Literal["turn_end"] = "turn_end"
    stop_reason: str | None = None


class PermissionAsked(Strict):
    kind: Literal["permission"] = "permission"
    request_id: str
    title: str | None = None
    tool_call_id: str | None = None
    options: list[PermissionOption]

    @field_serializer("options")
    def _options(self, options: list[PermissionOption]) -> list[JsonObject]:
        return [acp_json(o) for o in options]


class QuestionAsked(Strict):
    kind: Literal["question"] = "question"
    request_id: str
    message: str | None = None
    mode: str | None = None
    schema_: JsonObject | None = Field(default=None, alias="schema")
    url: str | None = None


class Resolved(Strict):
    """A permission or question was answered (client), withdrawn (agent) or dropped (runner)."""

    kind: Literal["resolved"] = "resolved"
    request_id: str
    by: Literal["client", "agent", "runner"]
    answer: Answer | None = None
    reason: str | None = None

    @field_serializer("answer")
    def _answer(self, answer: Answer | None) -> JsonObject | None:
        return None if answer is None else acp_json(answer)

    @model_serializer(mode="wrap")
    def _no_reason(self, handler: SerializerFunctionWrapHandler) -> dict[str, Any]:
        out: dict[str, Any] = handler(self)
        if out.get("reason") is None:
            out.pop("reason", None)  # given only when the runner dropped the request
        return out


class Cancelled(Strict):
    kind: Literal["cancel"] = "cancel"


class Failed(Strict):
    """Something failed: a turn (with the agent's error kind and data, if it gave them), a
    message from the agent that doesn't fit ACP, or the session itself."""

    kind: Literal["error"] = "error"
    message: str
    # The agent's own classification and its error's data, e.g. claude-agent-acp's
    # {"errorKind": "rate_limit", "rateLimit": {"resetsAt": ...}}.
    error_kind: str | None = None
    data: JsonValue = None

    @model_serializer(mode="wrap")
    def _only_given(self, handler: SerializerFunctionWrapHandler) -> dict[str, Any]:
        out: dict[str, Any] = handler(self)
        for key in ("error_kind", "data"):
            if out.get(key) is None:
                out.pop(key, None)
        return out


class Notified(Strict):
    """Alex was told something (notify-alex), or sending it failed."""

    kind: Literal["notified"] = "notified"
    message: str
    ok: bool
    error: str | None = None


class AgentNotification(Strict):
    """Any other notification from the agent (e.g. auth/status_update)."""

    kind: Literal["notification"] = "notification"
    method: str
    params: JsonObject


Body = Annotated[
    StateChanged
    | SessionOpened
    | Prompted
    | Updated
    | TurnEnded
    | PermissionAsked
    | QuestionAsked
    | Resolved
    | Cancelled
    | Failed
    | Notified
    | AgentNotification,
    Field(discriminator="kind"),
]

ENVELOPE = ("seq", "ts", "session")


class Event(Strict):
    seq: int
    ts: float
    session: str
    body: Body

    @property
    def kind(self) -> str:
        return self.body.kind

    @model_validator(mode="before")
    @classmethod
    def _nest(cls, data: Any) -> Any:
        """The flat wire form: the envelope's keys, the rest is the body."""
        if isinstance(data, dict) and "body" not in data:
            body = {k: v for k, v in data.items() if k not in ENVELOPE}
            return {**{k: data[k] for k in ENVELOPE if k in data}, "body": body}
        return data

    @model_serializer(mode="plain")
    def _flat(self) -> dict[str, Any]:
        body = self.body.model_dump(mode="json", by_alias=True)
        return {"seq": self.seq, "ts": self.ts, "session": self.session, **body}


class Heartbeat(Strict):
    """A live stream's keep-alive: not stored, no session; `seq` is the runner's latest."""

    kind: Literal["heartbeat"] = "heartbeat"
    ts: float
    seq: int


def decode_streamed(data: Any) -> Event | Heartbeat:
    """A line of an events stream: an event, or a heartbeat (ValidationError if neither)."""
    if isinstance(data, dict) and data.get("kind") == "heartbeat":
        return Heartbeat.model_validate(data)
    return Event.model_validate(data)
