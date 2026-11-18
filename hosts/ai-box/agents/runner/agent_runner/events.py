"""A session's events: what the event log stores and the API streams (README.md, "Events").

Every event is an `Event`: the envelope (`seq`, increasing across all sessions; `ts`; `session`)
and a body whose class gives its `kind`. On the wire the envelope and the body's fields are one
flat object: `{"seq": 1, "ts": ..., "session": "job", "kind": "state", "state": "idle", ...}`.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import ClassVar, Literal

from .acp import ElicitationResponse, PermissionOption, PermissionOutcome
from .schema import JsonObject, JsonValue, SchemaError, alias, decode, encode_object

# Session states (README.md, "States").
State = Literal[
    "starting", "running", "idle", "waiting", "offline", "failed", "stopped"
]
ENDED: frozenset[State] = frozenset({"failed", "stopped"})

# How `send` handed a message to the agent.
Delivery = Literal["sent", "steered", "queued"]


@dataclass(frozen=True, kw_only=True)
class StateChanged:
    KIND: ClassVar[str] = "state"
    state: State
    reason: str | None = None


@dataclass(frozen=True, kw_only=True)
class SessionOpened:
    """The agent's session was created or resumed."""

    KIND: ClassVar[str] = "session"
    agent_session_id: str
    transcript: str | None = None
    agent_info: JsonObject | None = None


@dataclass(frozen=True, kw_only=True)
class Prompted:
    KIND: ClassVar[str] = "prompt"
    text: str
    delivery: Delivery


@dataclass(frozen=True, kw_only=True)
class Updated:
    """An ACP session/update, as the agent sent it."""

    KIND: ClassVar[str] = "update"
    update: JsonObject


@dataclass(frozen=True, kw_only=True)
class TurnEnded:
    KIND: ClassVar[str] = "turn_end"
    stop_reason: str | None = None


@dataclass(frozen=True, kw_only=True)
class PermissionAsked:
    KIND: ClassVar[str] = "permission"
    request_id: str
    title: str | None = None
    tool_call_id: str | None = None
    options: list[PermissionOption]


@dataclass(frozen=True, kw_only=True)
class QuestionAsked:
    KIND: ClassVar[str] = "question"
    request_id: str
    message: str | None = None
    mode: str | None = None
    schema: JsonObject | None = None
    url: str | None = None


Asked = PermissionAsked | QuestionAsked


@dataclass(frozen=True, kw_only=True)
class Resolved:
    """A permission or question was answered (client), withdrawn (agent) or dropped (runner)."""

    KIND: ClassVar[str] = "resolved"
    request_id: str
    by: Literal["client", "agent", "runner"]
    answer: PermissionOutcome | ElicitationResponse | None = None
    reason: str | None = field(default=None, metadata=alias(omit_none=True))


@dataclass(frozen=True, kw_only=True)
class Cancelled:
    KIND: ClassVar[str] = "cancel"


@dataclass(frozen=True, kw_only=True)
class Failed:
    KIND: ClassVar[str] = "error"
    message: str


@dataclass(frozen=True, kw_only=True)
class Notified:
    """Alex was told about a failure (notify-alex), or telling him failed."""

    KIND: ClassVar[str] = "notified"
    message: str
    ok: bool
    error: str | None = None


@dataclass(frozen=True, kw_only=True)
class AgentNotification:
    """Any other notification from the agent (e.g. auth/status_update)."""

    KIND: ClassVar[str] = "notification"
    method: str
    params: JsonObject


Body = (
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
    | AgentNotification
)

BODIES: dict[str, type[Body]] = {
    cls.KIND: cls
    for cls in (
        StateChanged,
        SessionOpened,
        Prompted,
        Updated,
        TurnEnded,
        PermissionAsked,
        QuestionAsked,
        Resolved,
        Cancelled,
        Failed,
        Notified,
        AgentNotification,
    )
}

ENVELOPE = ("seq", "ts", "session", "kind")


@dataclass(frozen=True)
class Event:
    seq: int
    ts: float
    session: str
    body: Body

    @property
    def kind(self) -> str:
        return self.body.KIND

    def encode_json(self) -> JsonObject:
        out: JsonObject = {
            "seq": self.seq,
            "ts": self.ts,
            "session": self.session,
            "kind": self.kind,
        }
        out.update(encode_object(self.body))
        return out

    @classmethod
    def decode_json(cls, data: object, path: str = "") -> Event:
        if not isinstance(data, dict):
            raise SchemaError(path, "an event must be an object")
        envelope = decode(Envelope, {k: data[k] for k in ENVELOPE if k in data}, path)
        body_cls = BODIES.get(envelope.kind)
        if body_cls is None:
            raise SchemaError(f"{path}.kind" if path else "kind", "unknown event kind")
        fields = {k: v for k, v in data.items() if k not in ENVELOPE}
        return cls(
            envelope.seq, envelope.ts, envelope.session, decode(body_cls, fields, path)
        )


@dataclass(frozen=True)
class Envelope:
    seq: int
    ts: float
    session: str
    kind: str


@dataclass(frozen=True, kw_only=True)
class Heartbeat:
    """A live stream's keep-alive: not stored, no session; `seq` is the runner's latest."""

    kind: Literal["heartbeat"] = "heartbeat"
    ts: float
    seq: int


def decode_streamed(data: JsonValue) -> Event | Heartbeat:
    """A line of an events stream: an event, or a heartbeat."""
    if isinstance(data, dict) and data.get("kind") == "heartbeat":
        return decode(Heartbeat, data)
    return Event.decode_json(data)
