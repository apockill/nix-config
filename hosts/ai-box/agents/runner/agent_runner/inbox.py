"""What the agent sends a session: its updates, the requests that park until a client answers
them (permissions, questions), withdrawals, and everything else. A part of `Session`.

Everything the agent sends is handled in `observe`, which the SDK's connection calls in its read
loop for each message as it arrives, so events keep the agent's order (the SDK itself runs
notifications from a queue, behind the responses it resolves at once: the end of a turn would
overtake the agent's last words). A request that parks is announced there too, under its JSON-RPC
id (the SDK's handlers aren't given it; `$/cancel_request` names it); `handle`, the SDK's handler,
only awaits its reply, which the SDK then sends.
"""

from __future__ import annotations

import asyncio
from collections import defaultdict, deque
from typing import Any

from acp.connection import StreamDirection, StreamEvent
from acp.exceptions import RequestError
from acp.meta import CLIENT_METHODS
from acp.schema import (
    AgentMessageChunk,
    CancelRequestNotification,
    RequestPermissionRequest,
    SessionInfoUpdate,
    TextContentBlock,
)
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from .base import JsonObject, describe
from .events import (
    AgentNotification,
    Body,
    Event,
    Failed,
    PermissionAsked,
    QuestionAsked,
    Resolved,
    Updated,
)
from .parking import Parking, Reply, RpcId, outcome
from .store import Record

UPDATE = CLIENT_METHODS["session_update"]
PERMISSION = CLIENT_METHODS["session_request_permission"]
QUESTION = CLIENT_METHODS["elicitation_create"]
WITHDRAW = "$/cancel_request"


class ElicitationRequest(BaseModel):
    """elicitation/create (Claude's AskUserQuestion). The SDK's own model of it (0.10) drops the
    form's requestedSchema, which is the question's fields, so the runner reads it itself.
    """

    model_config = ConfigDict(populate_by_name=True)

    message: str
    mode: str | None = None
    requested_schema: JsonObject | None = Field(default=None, alias="requestedSchema")
    url: str | None = None


class UpdateEnvelope(BaseModel):
    """session/update as the runner checks it: the session, and an update that says its kind.
    The update itself goes on unchanged; agents add kinds the SDK doesn't know yet."""

    session_id: str = Field(alias="sessionId")
    update: JsonObject

    @field_validator("update")
    @classmethod
    def _says_its_kind(cls, update: JsonObject) -> JsonObject:
        if not isinstance(update.get("sessionUpdate"), str):
            raise ValueError("sessionUpdate must be a string")
        return update

    @property
    def kind(self) -> object:
        return self.update["sessionUpdate"]


class Inbox:
    """The agent's messages to a session (Session's base: these use its state)."""

    record: Record
    parking: Parking
    first_update: asyncio.Event
    muted: bool
    last_text: str
    # The replies `handle` awaits, by method, in the order the requests came (None: it didn't fit).
    waiting: defaultdict[str, deque[asyncio.Future[Reply] | None]]

    def emit(self, body: Body) -> Event:
        raise NotImplementedError

    def settle_state(self) -> None:
        raise NotImplementedError

    def save(self) -> None:
        raise NotImplementedError

    def parked(self, event: Event) -> None:
        raise NotImplementedError

    @property
    def name(self) -> str:
        return self.record.name

    def observe(self, event: StreamEvent) -> None:
        """Every message from the agent, in the read loop, in the order it came: notifications
        are handled here (the SDK would queue them behind responses), and a request that parks is
        announced here, its reply awaited by `handle`. It must not raise (the SDK logs it).
        """
        message = event.message
        method = message.get("method")
        if event.direction is not StreamDirection.INCOMING or not isinstance(
            method, str
        ):
            return
        params = message.get("params")
        if "id" not in message:
            self.notified_by_agent(method, params)
        elif method in (PERMISSION, QUESTION):
            self.waiting[method].append(
                self.asked_by_agent(method, message["id"], params)
            )

    def notified_by_agent(self, method: str, params: Any) -> None:
        try:
            if method == UPDATE:
                self.on_update(UpdateEnvelope.model_validate(params))
            elif method == WITHDRAW:
                self.on_withdraw(CancelRequestNotification.model_validate(params))
            else:
                self.emit(AgentNotification(method=method, params=params or {}))
        except ValidationError as e:
            self.misfit(method, e)

    def asked_by_agent(
        self, method: str, rpc_id: RpcId, params: Any
    ) -> asyncio.Future[Reply] | None:
        """Park the request; None (and an error event) if it doesn't fit ACP."""
        try:
            if method == PERMISSION:
                req = RequestPermissionRequest.model_validate(params)
                asked: PermissionAsked | QuestionAsked = PermissionAsked(
                    request_id=self.parking.next_id("permission"),
                    title=req.tool_call.title,
                    tool_call_id=req.tool_call.tool_call_id,
                    options=req.options,
                )
            else:
                q = ElicitationRequest.model_validate(params)
                asked = QuestionAsked(
                    request_id=self.parking.next_id("question"),
                    message=q.message,
                    mode=q.mode,
                    schema=q.requested_schema,
                    url=q.url,
                )
        except ValidationError as e:
            self.misfit(method, e)
            return None
        event = self.emit(asked)
        reply = self.parking.park(rpc_id, event)
        self.parked(event)
        self.first_update.set()
        self.settle_state()
        return reply

    def misfit(self, method: str, error: ValidationError) -> None:
        # Loud, not fatal: the session says why and counts them (status's misfits), and the SDK
        # refuses a request that doesn't fit.
        self.record.misfits += 1
        self.save()
        self.emit(
            Failed(
                message=f"the agent sent a {method} that doesn't fit ACP: {describe(error)}"
            )
        )

    async def handle(self, method: str, params: Any, is_notification: bool) -> Any:
        """The SDK's handler, in a task per message: a parked request's reply, once it comes."""
        if is_notification:
            return None  # observe() has handled it
        if method in (PERMISSION, QUESTION):
            reply = self.waiting[method].popleft() if self.waiting[method] else None
            if reply is None:  # it didn't fit: the SDK answers invalid params
                model = (
                    RequestPermissionRequest
                    if method == PERMISSION
                    else ElicitationRequest
                )
                model.model_validate(params)
                raise RequestError.invalid_params({"method": method})
            return await reply
        raise RequestError.method_not_found(method)

    def on_update(self, note: UpdateEnvelope) -> None:
        event = Updated(update=note.update)
        if note.kind in ("session_info_update", "agent_message_chunk"):
            self.look_into(event)
        if not self.muted:
            self.emit(event)
            self.first_update.set()

    def look_into(self, event: Updated) -> None:
        """The two updates the runner reads: the conversation's title, the agent's text."""
        parsed = event.parsed()
        if isinstance(parsed, SessionInfoUpdate) and parsed.title:
            self.record.title = parsed.title
        if (
            not self.muted
            and isinstance(parsed, AgentMessageChunk)
            and isinstance(parsed.content, TextContentBlock)
        ):
            self.last_text += parsed.content.text

    def on_withdraw(self, req: CancelRequestNotification) -> None:
        if req.request_id is None:
            return
        for request_id in self.parking.withdraw(req.request_id):
            self.emit(Resolved(request_id=request_id, by="agent"))
        self.settle_state()

    def drop_pending(self, why: str) -> None:
        for request_id in self.parking.drop():
            self.emit(Resolved(request_id=request_id, by="runner", reason=why))

    # Answers
    def answer(self, request_id: str, body: JsonObject) -> None:
        self.resolved(request_id, self.parking.answer(self.name, request_id, body))

    def resolved(self, request_id: str, reply: Reply) -> None:
        self.emit(Resolved(request_id=request_id, by="client", answer=outcome(reply)))
        self.settle_state()
