"""What the agent sends a session: its updates, the requests that park until a client answers
them (permissions, questions), withdrawals, and everything else. A part of `Session`."""

from __future__ import annotations

import asyncio

from . import acp
from .acp import RpcId
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
from .parking import Answer, Parking
from .rpc import Connection
from .schema import JsonObject, SchemaError, decode
from .store import Record
from .updates import session_title


class Inbox:
    """The agent's messages to a session (Session's base: these use its state)."""

    record: Record
    conn: Connection | None
    parking: Parking
    first_update: asyncio.Event
    muted: bool

    @property
    def name(self) -> str:
        return self.record.name

    def emit(self, body: Body) -> Event:
        raise NotImplementedError

    def settle_state(self) -> None:
        raise NotImplementedError

    async def on_message(
        self, method: str, params: JsonObject, rid: RpcId | None
    ) -> None:
        try:
            if method == "session/update":
                self.on_update(decode(acp.SessionNotification, params))
            elif method == "session/request_permission" and rid is not None:
                self.on_permission(rid, decode(acp.RequestPermissionParams, params))
            elif method == "elicitation/create" and rid is not None:
                self.on_question(rid, decode(acp.ElicitationParams, params))
            elif method == "$/cancel_request":
                self.on_withdraw(decode(acp.CancelRequestParams, params))
            elif rid is not None:
                assert self.conn
                self.conn.respond_error(
                    rid,
                    acp.METHOD_NOT_FOUND,
                    f"agent-runner doesn't implement {method}",
                )
            else:
                self.emit(AgentNotification(method=method, params=params))
        except SchemaError as e:
            # Loud, not fatal: the agent's request is refused and the session says why.
            self.emit(
                Failed(message=f"the agent sent a {method} that doesn't fit ACP: {e}")
            )
            if rid is not None and self.conn:
                self.conn.respond_error(rid, acp.INVALID_PARAMS, str(e))

    def on_update(self, note: acp.SessionNotification) -> None:
        if title := session_title(note.update):
            self.record.title = title
        if not self.muted:
            self.emit(Updated(update=note.update))
            self.first_update.set()

    def on_permission(self, rid: RpcId, req: acp.RequestPermissionParams) -> None:
        asked = PermissionAsked(
            request_id=self.parking.next_id("permission"),
            title=req.tool_call.title,
            tool_call_id=req.tool_call.tool_call_id,
            options=req.options,
        )
        self.park(rid, asked)

    def on_question(self, rid: RpcId, req: acp.ElicitationParams) -> None:
        asked = QuestionAsked(
            request_id=self.parking.next_id("question"),
            message=req.message,
            mode=req.mode,
            schema=req.requested_schema,
            url=req.url,
        )
        self.park(rid, asked)

    def park(self, rid: RpcId, asked: PermissionAsked | QuestionAsked) -> None:
        self.parking.park(rid, self.emit(asked))
        self.first_update.set()
        self.settle_state()

    def on_withdraw(self, req: acp.CancelRequestParams) -> None:
        for request_id in self.parking.withdraw(req.request_id):
            self.emit(Resolved(request_id=request_id, by="agent"))
        self.settle_state()

    def drop_pending(self, why: str) -> None:
        for request_id in self.parking.drop():
            self.emit(Resolved(request_id=request_id, by="runner", reason=why))

    # Answers
    def answer(self, request_id: str, body: JsonObject) -> None:
        self.deliver(request_id, self.parking.answer(self.name, request_id, body))

    def deliver(self, request_id: str, answer: Answer) -> None:
        assert self.conn
        self.conn.respond(answer.rpc_id, answer.response)
        self.emit(Resolved(request_id=request_id, by="client", answer=answer.outcome))
        self.settle_state()
