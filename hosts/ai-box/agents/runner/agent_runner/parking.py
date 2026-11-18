"""Requests from the agent that wait for an answer: permissions and questions.

The agent's request is parked under an id of the runner's (`p1`, `q2`: permission or question)
until a client answers it, the agent withdraws it, or the runner drops it (stop, the agent exited).
Nobody needs to be attached while it waits: that's the normal case for a job.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

from .acp import (
    ElicitationResponse,
    PermissionOutcome,
    RequestPermissionResponse,
    RpcId,
)
from .errors import RunnerError
from .events import Event, PermissionAsked, QuestionAsked
from .schema import JsonObject, SchemaError, decode


@dataclass(frozen=True, kw_only=True)
class PermissionAnswer:
    """`POST .../requests/p<n>`: one of the request's options, or cancel."""

    option_id: str | None = None
    cancel: bool = False


@dataclass(frozen=True, kw_only=True)
class QuestionAnswer:
    """`POST .../requests/q<n>`: accept with the form's fields, decline, or cancel."""

    action: Literal["accept", "decline", "cancel"]
    content: JsonObject | None = None


@dataclass(frozen=True)
class Pending:
    """A parked request: the agent's JSON-RPC id, and the event that announced it."""

    rpc_id: RpcId
    event: Event

    @property
    def kind(self) -> Literal["permission", "question"]:
        return (
            "permission" if isinstance(self.event.body, PermissionAsked) else "question"
        )


@dataclass(frozen=True)
class Answer:
    """What goes back to the agent for a parked request, and what the `resolved` event says."""

    rpc_id: RpcId
    response: RequestPermissionResponse | ElicitationResponse

    @property
    def outcome(self) -> PermissionOutcome | ElicitationResponse:
        r = self.response
        return r.outcome if isinstance(r, RequestPermissionResponse) else r


@dataclass
class Parking:
    """One session's parked requests, in the order they came."""

    open: dict[str, Pending] = field(default_factory=dict)
    next_number: int = 1

    def next_id(self, kind: Literal["permission", "question"]) -> str:
        request_id = f"{kind[0]}{self.next_number}"
        self.next_number += 1
        return request_id

    def park(self, rpc_id: RpcId, event: Event) -> None:
        body = event.body
        assert isinstance(body, PermissionAsked | QuestionAsked)
        self.open[body.request_id] = Pending(rpc_id, event)

    def answer(self, session: str, request_id: str, body: JsonObject) -> Answer:
        """Check a client's answer and unpark the request; RunnerError if it doesn't fit."""
        pending = self.open.get(request_id)
        if pending is None:
            raise RunnerError(f"{session} has no open request {request_id}", 404)
        answer = Answer(pending.rpc_id, self._response(pending, body))
        del self.open[request_id]
        return answer

    def cancel(self, request_id: str) -> Answer:
        """Unpark a request with a cancel: what `cancel` does to every open one."""
        pending = self.open.pop(request_id)
        response: RequestPermissionResponse | ElicitationResponse = (
            RequestPermissionResponse(PermissionOutcome(outcome="cancelled"))
            if pending.kind == "permission"
            else ElicitationResponse(action="cancel")
        )
        return Answer(pending.rpc_id, response)

    def withdraw(self, rpc_id: RpcId) -> list[str]:
        """The agent took back its request ($/cancel_request): the ids unparked."""
        ids = [rid for rid, p in self.open.items() if p.rpc_id == rpc_id]
        for request_id in ids:
            del self.open[request_id]
        return ids

    def drop(self) -> list[str]:
        """Unpark everything (stop, the agent exited): the ids unparked."""
        ids = list(self.open)
        self.open.clear()
        return ids

    @staticmethod
    def _response(
        pending: Pending, body: JsonObject
    ) -> RequestPermissionResponse | ElicitationResponse:
        asked = pending.event.body
        try:
            if isinstance(asked, PermissionAsked):
                p = decode(PermissionAnswer, body)
                if p.cancel:
                    return RequestPermissionResponse(
                        PermissionOutcome(outcome="cancelled")
                    )
                ids = [o.option_id for o in asked.options]
                if p.option_id not in ids:
                    raise RunnerError(f"option_id must be one of {', '.join(ids)}")
                return RequestPermissionResponse(
                    PermissionOutcome(outcome="selected", option_id=p.option_id)
                )
            q = decode(QuestionAnswer, body)
        except SchemaError as e:
            raise RunnerError.bad_request(e) from e
        if q.action != "accept":
            return ElicitationResponse(action=q.action)
        if q.content is None:
            raise RunnerError("accept needs content: an object of the schema's fields")
        return ElicitationResponse(action="accept", content=q.content)
