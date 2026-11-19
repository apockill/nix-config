"""Requests from the agent that wait for an answer: permissions and questions.

The agent's request is parked under an id of the runner's (`p1`, `q2`: permission or question)
until a client answers it, the agent withdraws it, or the runner drops it (stop, the agent exited).
Nobody needs to be attached while it waits: that's the normal case for a job. Each parked request
is a future that the SDK's handler for it awaits: answering resolves it, and the SDK sends the
reply; withdrawing or dropping cancels it, and nothing is sent.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Literal

from acp.schema import (
    AcceptElicitationResponse,
    AllowedOutcome,
    CancelElicitationResponse,
    DeclineElicitationResponse,
    DeniedOutcome,
    RequestPermissionResponse,
)
from pydantic import ValidationError

from .base import JsonObject, Strict
from .errors import RunnerError
from .events import Answer, Event, PermissionAsked, QuestionAsked

type RpcId = int | str
QuestionReply = (
    AcceptElicitationResponse | DeclineElicitationResponse | CancelElicitationResponse
)
Reply = RequestPermissionResponse | QuestionReply


class PermissionAnswer(Strict):
    """`POST .../requests/p<n>`: one of the request's options, or cancel."""

    option_id: str | None = None
    cancel: bool = False


class QuestionAnswer(Strict):
    """`POST .../requests/q<n>`: accept with the form's fields, decline, or cancel."""

    action: Literal["accept", "decline", "cancel"]
    content: JsonObject | None = None


@dataclass
class Pending:
    """A parked request: the agent's JSON-RPC id, the event that announced it, its reply."""

    rpc_id: RpcId | None
    event: Event
    reply: asyncio.Future[Reply] = field(
        default_factory=lambda: asyncio.get_running_loop().create_future()
    )

    @property
    def kind(self) -> Literal["permission", "question"]:
        return (
            "permission" if isinstance(self.event.body, PermissionAsked) else "question"
        )


def outcome(reply: Reply) -> Answer:
    """What the `resolved` event says was answered."""
    return reply.outcome if isinstance(reply, RequestPermissionResponse) else reply


@dataclass
class Parking:
    """One session's parked requests, in the order they came."""

    open: dict[str, Pending] = field(default_factory=dict)
    next_number: int = 1

    def next_id(self, kind: Literal["permission", "question"]) -> str:
        request_id = f"{kind[0]}{self.next_number}"
        self.next_number += 1
        return request_id

    def park(self, rpc_id: RpcId | None, event: Event) -> asyncio.Future[Reply]:
        body = event.body
        assert isinstance(body, PermissionAsked | QuestionAsked)
        pending = Pending(rpc_id, event)
        self.open[body.request_id] = pending
        return pending.reply

    def answer(self, session: str, request_id: str, body: JsonObject) -> Reply:
        """Check a client's answer and send it; RunnerError if it doesn't fit."""
        pending = self.open.get(request_id)
        if pending is None:
            raise RunnerError(f"{session} has no open request {request_id}", 404)
        return self._send(request_id, reply_to(pending, body))

    def cancel(self, request_id: str) -> Reply:
        """Answer a request with a cancel: what `cancel` does to every open one."""
        pending = self.open[request_id]
        reply: Reply = (
            RequestPermissionResponse(outcome=DeniedOutcome(outcome="cancelled"))
            if pending.kind == "permission"
            else CancelElicitationResponse(action="cancel")
        )
        return self._send(request_id, reply)

    def _send(self, request_id: str, reply: Reply) -> Reply:
        pending = self.open.pop(request_id)
        if not pending.reply.done():
            pending.reply.set_result(reply)
        return reply

    def withdraw(self, rpc_id: RpcId) -> list[str]:
        """The agent took back its request ($/cancel_request): the ids unparked, unanswered."""
        return self._drop([r for r, p in self.open.items() if p.rpc_id == rpc_id])

    def drop(self) -> list[str]:
        """Unpark everything, unanswered (stop, the agent exited): the ids unparked."""
        return self._drop(list(self.open))

    def _drop(self, ids: list[str]) -> list[str]:
        for request_id in ids:
            self.open.pop(request_id).reply.cancel()
        return ids


def reply_to(pending: Pending, body: JsonObject) -> Reply:
    asked = pending.event.body
    try:
        if isinstance(asked, PermissionAsked):
            p = PermissionAnswer.model_validate(body)
            if p.cancel:
                return RequestPermissionResponse(
                    outcome=DeniedOutcome(outcome="cancelled")
                )
            ids = [o.option_id for o in asked.options]
            if p.option_id not in ids:
                raise RunnerError(f"option_id must be one of {', '.join(ids)}")
            return RequestPermissionResponse(
                outcome=AllowedOutcome(outcome="selected", option_id=p.option_id)
            )
        q = QuestionAnswer.model_validate(body)
    except ValidationError as e:
        raise RunnerError.bad_request(e) from e
    if q.action == "decline":
        return DeclineElicitationResponse(action="decline")
    if q.action == "cancel":
        return CancelElicitationResponse(action="cancel")
    if q.content is None:
        raise RunnerError("accept needs content: an object of the schema's fields")
    return AcceptElicitationResponse(action="accept", content=q.content)
