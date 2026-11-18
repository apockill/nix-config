"""The API (README.md) as a Starlette app: each request body checked by its model, each answer a
model, every error `{"error": ...}` with its status, events as NDJSON."""

from __future__ import annotations

import asyncio
import json
import sys
import time
from collections.abc import AsyncIterator, Awaitable, Callable

from pydantic import BaseModel, ValidationError
from starlette.applications import Starlette
from starlette.exceptions import HTTPException
from starlette.requests import Request
from starlette.responses import JSONResponse, Response, StreamingResponse
from starlette.routing import Route, request_response
from starlette.types import ASGIApp

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

DOCS = "see agents/runner/README.md"
# Where server.py's protocol puts the calling process's pid (the socket's SO_PEERCRED).
PEER_PID = "agent_runner.peer_pid"


def answer(model: BaseModel, code: int = 200) -> Response:
    return JSONResponse(model.model_dump(mode="json", by_alias=True), code)


def error(message: str, code: int, resets_at: float | None = None) -> Response:
    body = ErrorBody(error=message, resets_at=resets_at)
    return JSONResponse(body.model_dump(exclude_none=True), code)


async def body_of(request: Request) -> JsonObject:
    raw = await request.body()
    try:
        body = json.loads(raw) if raw else {}
    except ValueError as e:
        raise RunnerError(f"the body isn't JSON: {e}") from e
    if not isinstance(body, dict):
        raise RunnerError("the body must be a JSON object")
    return body


async def body_as[M: BaseModel](request: Request, model: type[M]) -> M:
    try:
        return model.model_validate(await body_of(request))
    except ValidationError as e:
        raise RunnerError.bad_request(e) from e


def number(request: Request, name: str, default: int) -> int:
    value = request.query_params.get(name)
    if value in (None, ""):
        return default
    assert value is not None
    if not value.isdigit():
        raise RunnerError(f"{name}: a whole number, not {value!r}")
    return int(value)


def name_of(request: Request) -> str:
    name: str = request.path_params["name"]
    return name


class Api:
    def __init__(self, runner: Runner, stop: asyncio.Event) -> None:
        self.runner = runner
        # Set by POST /v1/restart, after the answer has gone out.
        self.stop = stop
        self.restart_requested = False

    def app(self) -> Starlette:
        r = self.runner

        async def restart(request: Request) -> Response:
            force = (await body_as(request, RestartRequest)).force
            if (busy := r.busy()) and not force:
                raise RunnerError(
                    f"{', '.join(busy)} would lose their running turn or open request;"
                    " wait for them, or restart with force (`agent restart --force`)",
                    409,
                )
            self.restart_requested = True
            asyncio.get_running_loop().call_later(0.2, self.stop.set)
            return answer(Restarting())

        async def agents(request: Request) -> Response:
            return answer(
                AgentList(
                    default=r.config.default_agent, agents=sorted(r.config.agents)
                )
            )

        async def sessions(request: Request) -> Response:
            return answer(SessionList(sessions=r.summaries()))

        async def start(request: Request) -> Response:
            return answer(
                status(await r.start(await body_as(request, StartRequest))), 201
            )

        async def one(request: Request) -> Response:
            return answer(status(r.get(name_of(request))))

        async def output(request: Request) -> Response:
            lines = number(request, "lines", 40)
            rendered = render(r.get(name_of(request)).files.read_events())
            return answer(Output(lines=rendered[-lines:] if lines else []))

        async def send(request: Request) -> Response:
            text = (await body_as(request, SendRequest)).text
            if not text.strip():
                raise RunnerError("text: the message")
            return answer(Sent(delivery=await r.get(name_of(request)).send(text)))

        async def cancel(request: Request) -> Response:
            await body_as(request, EmptyRequest)
            await r.get(name_of(request)).cancel()
            return answer(status(r.get(name_of(request))))

        async def stop(request: Request) -> Response:
            reason = (await body_as(request, StopRequest)).reason
            await r.get(name_of(request)).stop(reason or "stopped")
            return answer(status(r.get(name_of(request))))

        async def reply(request: Request) -> Response:
            session = r.get(name_of(request))
            session.answer(request.path_params["request_id"], await body_of(request))
            return answer(status(session))

        async def events(request: Request) -> Response:
            only = request.path_params.get("name")
            session = (
                r.get(only) if only else None
            )  # an unknown one is a 404, not a stream
            since = number(request, "since", 0)
            follow = request.query_params.get("follow") in ("1", "true", "yes")
            stream = self.events(session, since, follow)
            return StreamingResponse(stream, media_type="application/x-ndjson")

        routes = [
            Route("/v1/restart", restart, methods=["POST"]),
            Route("/v1/agents", agents, methods=["GET"]),
            Route("/v1/sessions", sessions, methods=["GET"]),
            Route("/v1/sessions", start, methods=["POST"]),
            Route("/v1/events", events, methods=["GET"]),
            Route("/v1/sessions/{name}", one, methods=["GET"]),
            Route("/v1/sessions/{name}/output", output, methods=["GET"]),
            Route("/v1/sessions/{name}/events", events, methods=["GET"]),
            Route("/v1/sessions/{name}/send", send, methods=["POST"]),
            Route("/v1/sessions/{name}/cancel", cancel, methods=["POST"]),
            Route("/v1/sessions/{name}/stop", stop, methods=["POST"]),
            Route("/v1/sessions/{name}/requests/{request_id}", reply, methods=["POST"]),
        ]
        # The router's own 404 and 405; an endpoint's failures are answered by `guarded`.
        handlers: dict[
            type[Exception] | int, Callable[[Request, Exception], Awaitable[Response]]
        ] = {HTTPException: self.http_error}
        for route in routes:
            route.app = guarded(route.endpoint, self.admit)
        return Starlette(routes=routes, exception_handlers=handlers)

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


Endpoint = Callable[[Request], Awaitable[Response]]


def guarded(endpoint: Endpoint, admit: Callable[[Request], None]) -> ASGIApp:
    """An endpoint for callers `admit` lets in, whose failures are answers: RunnerError with its
    status, anything else a 500 (logged). Answered here rather than by an exception handler,
    which Starlette re-raises after, closing the connection (a client's next call on it was
    reset)."""

    async def run(request: Request) -> Response:
        try:
            admit(request)
            return await endpoint(request)
        except RunnerError as e:
            return error(str(e), e.status, e.resets_at)
        except Exception as e:  # one bad request mustn't end the service
            print(
                f"agent-runner: {request.method} {request.url.path}: {e!r}",
                file=sys.stderr,
            )
            return error(f"internal error: {e!r}", 500)

    return request_response(run)


def line(item: Event | Heartbeat) -> bytes:
    return json.dumps(item.model_dump(mode="json"), ensure_ascii=False).encode() + b"\n"
