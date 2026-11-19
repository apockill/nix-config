"""The API (api_types.py) as a FastAPI app: each route declared with its body, parameters and
answer models (GET /v1/openapi.json describes them), every error `{"error": ...}` with its status,
events as NDJSON. `guarded` keeps the runner's own answers where FastAPI's differ."""

from __future__ import annotations

import asyncio
import json
import sys
import time
from collections.abc import AsyncIterator, Callable, Coroutine
from typing import Annotated, Any

from fastapi import Body, FastAPI, Query
from fastapi.exceptions import RequestValidationError
from fastapi.routing import APIRoute
from pydantic import BeforeValidator
from pydantic_core import PydanticCustomError, PydanticUseDefault
from starlette.exceptions import HTTPException
from starlette.requests import Request
from starlette.responses import JSONResponse, Response, StreamingResponse
from starlette.types import Message

from .api_types import (
    AgentList,
    EmptyRequest,
    ErrorBody,
    Output,
    Restarting,
    RestartRequest,
    SendRequest,
    Sent,
    SessionList,
    SessionStatus,
    StartRequest,
    StopRequest,
)
from .base import JsonObject
from .config import HEARTBEAT_SECONDS
from .errors import RunnerError
from .events import Event, Heartbeat
from .render import render
from .runner import Runner, status
from .session import Session

DOCS = "see agents/runner/agent_runner/api_types.py"
# Where server.py's protocol puts the calling process's pid (the socket's SO_PEERCRED).
PEER_PID = "agent_runner.peer_pid"


def error(message: str, code: int, resets_at: float | None = None) -> Response:
    body = ErrorBody(error=message, resets_at=resets_at)
    return JSONResponse(body.model_dump(exclude_none=True), code)


def _whole(value: object) -> object:
    if value == "":
        raise PydanticUseDefault()
    if isinstance(value, str) and not (value.isascii() and value.isdigit()):
        raise PydanticCustomError(
            "whole_number", "a whole number, not {value}", {"value": repr(value)}
        )
    return value


# Query parameters: a whole number (empty is the default), and a flag that is on as 1, true or yes.
Whole = Annotated[int, Query(ge=0), BeforeValidator(_whole)]
Flag = Annotated[bool, BeforeValidator(lambda v: v in ("1", "true", "yes"))]


def fails(*codes: int, streams: bool = False) -> dict[int | str, dict[str, Any]]:
    """A route's error answers for the schema: its own statuses, 403 (`admit`), and the rest."""
    # A stream's errors are JSON too (FastAPI would list a model under the route's media type).
    json_ref = {"schema": {"$ref": "#/components/schemas/ErrorBody"}}
    err: dict[str, Any] = (
        {"content": {"application/json": json_ref}} if streams else {"model": ErrorBody}
    )
    return {
        **(
            {200: {"description": "NDJSON: an Event per line, and heartbeats"}}
            if streams
            else {}
        ),
        **{code: err for code in (*codes, 403)},
        "default": {**err, "description": "a 500, or the agent's 429, 502, 504"},
    }


class Ndjson(StreamingResponse):
    media_type = "application/x-ndjson"


class Api:
    def __init__(self, runner: Runner, stop: asyncio.Event) -> None:
        self.runner = runner
        # Set by POST /v1/restart, after the answer has gone out.
        self.stop = stop
        self.restart_requested = False

    def app(self) -> FastAPI:
        r = self.runner
        # The schema is open to every caller (it says nothing a caller couldn't read in
        # api_types.py), so it isn't a guarded route; no /docs or /redoc: no browser reads a unix
        # socket, and their pages load from a CDN.
        app = FastAPI(
            title="agent runner",
            description=DOCS,
            openapi_url="/v1/openapi.json",
            docs_url=None,
            redoc_url=None,
            # The router's own 404 and 405; a route's failures are answered by `guarded`.
            exception_handlers={HTTPException: self.http_error},
        )
        app.router.route_class = guarded(self.admit)

        @app.post("/v1/restart", responses=fails(400, 409))
        async def restart(body: RestartRequest) -> Restarting:
            if (busy := r.busy()) and not body.force:
                raise RunnerError(
                    f"{', '.join(busy)} would lose their running turn or open request;"
                    " wait for them, or restart with force (`agent restart --force`)",
                    409,
                )
            self.restart_requested = True
            asyncio.get_running_loop().call_later(0.2, self.stop.set)
            return Restarting()

        @app.get("/v1/agents", responses=fails())
        async def agents() -> AgentList:
            return AgentList(
                default=r.config.default_agent, agents=sorted(r.config.agents)
            )

        @app.get("/v1/sessions", responses=fails())
        async def sessions() -> SessionList:
            return SessionList(sessions=r.summaries())

        @app.post("/v1/sessions", status_code=201, responses=fails(400, 409))
        async def start(body: StartRequest) -> SessionStatus:
            return status(await r.start(body))

        @app.get(
            "/v1/events", response_class=Ndjson, responses=fails(400, streams=True)
        )
        async def events(since: Whole = 0, follow: Flag = False) -> Ndjson:
            return Ndjson(self.events(None, since, follow))

        @app.get("/v1/sessions/{name}", responses=fails(404))
        async def one(name: str) -> SessionStatus:
            return status(r.get(name))

        @app.get("/v1/sessions/{name}/output", responses=fails(400, 404))
        async def output(name: str, lines: Whole = 40) -> Output:
            rendered = render(r.get(name).files.read_events())
            return Output(lines=rendered[-lines:] if lines else [])

        @app.get(
            "/v1/sessions/{name}/events",
            response_class=Ndjson,
            responses=fails(400, 404, streams=True),
        )
        async def session_events(
            name: str, since: Whole = 0, follow: Flag = False
        ) -> Ndjson:
            # An unknown session is a 404, not a stream.
            return Ndjson(self.events(r.get(name), since, follow))

        @app.post("/v1/sessions/{name}/send", responses=fails(400, 404, 409))
        async def send(name: str, body: SendRequest) -> Sent:
            if not body.text.strip():
                raise RunnerError("text: the message")
            return Sent(delivery=await r.get(name).send(body.text))

        @app.post("/v1/sessions/{name}/cancel", responses=fails(400, 404))
        async def cancel(name: str, body: EmptyRequest) -> SessionStatus:
            await r.get(name).cancel()
            return status(r.get(name))

        @app.post("/v1/sessions/{name}/stop", responses=fails(400, 404))
        async def stop(name: str, body: StopRequest) -> SessionStatus:
            await r.get(name).stop(body.reason or "stopped")
            return status(r.get(name))

        @app.post(
            "/v1/sessions/{name}/requests/{request_id}", responses=fails(400, 404)
        )
        async def reply(
            name: str,
            request_id: str,
            # parking.PermissionAnswer or QuestionAnswer, checked by the session.
            body: Annotated[JsonObject, Body()],
        ) -> SessionStatus:
            session = r.get(name)
            session.answer(request_id, body)
            return status(session)

        return app

    def admit(self, request: Request) -> None:
        """RunnerError 403 for a caller inside a session that may not use the runner."""
        pid = request.scope.get(PEER_PID)
        self.runner.admit(pid if isinstance(pid, int) else None)

    async def events(
        self, session: Session | None, since: int, follow: bool
    ) -> AsyncIterator[bytes]:
        """The stored events after `since`, then, following, the live ones and heartbeats."""
        only = session.name if session else None
        async with self.runner.bus.subscribe() as queue:
            history = (
                list(session.files.read_events(since))
                if session
                else self.runner.bus.recent(since)
            )
            last = since
            for event in history:
                yield line(event)
                last = event.seq
            while follow:
                try:
                    event = await asyncio.wait_for(queue.get(), HEARTBEAT_SECONDS)
                except TimeoutError:
                    yield line(Heartbeat(ts=time.time(), seq=self.runner.bus.seq))
                    continue
                if event.seq > last and (not only or event.session == only):
                    yield line(event)

    @staticmethod
    async def http_error(request: Request, exc: Exception) -> Response:
        assert isinstance(exc, HTTPException)
        if exc.status_code == 404:
            return error(f"no {request.method} {request.url.path}; {DOCS}", 404)
        return error(
            f"{exc.detail}: {request.method} {request.url.path}; {DOCS}",
            exc.status_code,
        )


Handler = Callable[[Request], Coroutine[Any, Any, Response]]


def guarded(admit: Callable[[Request], None]) -> type[APIRoute]:
    """Routes for callers `admit` lets in (before their body is read), whose failures are
    answers: RunnerError with its status, a body or parameter that doesn't fit a 400 naming the
    field, anything else a 500 (logged). Answered here rather than by an exception handler, which
    Starlette re-raises after for a 500, closing the connection (a client's next call on it was
    reset)."""

    class Guarded(APIRoute):
        def get_route_handler(self) -> Handler:
            handler = super().get_route_handler()
            reads_body = self.body_field is not None

            async def run(request: Request) -> Response:
                try:
                    admit(request)
                    return await handler(
                        await as_json(request) if reads_body else request
                    )
                except RequestValidationError as e:
                    return error(described(e), 400)
                except RunnerError as e:
                    return error(str(e), e.status, e.resets_at)
                except Exception as e:  # one bad request mustn't end the service
                    print(
                        f"agent-runner: {request.method} {request.url.path}: {e!r}",
                        file=sys.stderr,
                    )
                    return error(f"internal error: {e!r}", 500)

            return run

    return Guarded


async def as_json(request: Request) -> Request:
    """The request, its body a JSON object (an empty body `{}`) and said to be one whatever its
    Content-Type: FastAPI would read only application/json and answer bad JSON its own way.
    """
    raw = await request.body()
    try:
        body = json.loads(raw) if raw else {}
    except ValueError as e:
        raise RunnerError(f"the body isn't JSON: {e}") from e
    if not isinstance(body, dict):
        raise RunnerError("the body must be a JSON object")
    headers = [(k, v) for k, v in request.scope["headers"] if k != b"content-type"]
    scope = {
        **request.scope,
        "headers": [*headers, (b"content-type", b"application/json")],
    }

    async def receive() -> Message:
        return {"type": "http.request", "body": raw or b"{}", "more_body": False}

    return Request(scope, receive)


def described(e: RequestValidationError) -> str:
    """`base.describe`'s line for FastAPI's errors: each field without the `body.` or `query.`."""
    parts = []
    for err in e.errors():
        where = ".".join(str(p) for p in err["loc"][1:])
        parts.append(f"{where}: {err['msg']}" if where else err["msg"])
    return "; ".join(parts)


def line(item: Event | Heartbeat) -> bytes:
    return json.dumps(item.model_dump(mode="json"), ensure_ascii=False).encode() + b"\n"
