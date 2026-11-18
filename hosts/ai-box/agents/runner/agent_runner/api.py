"""The API's routes (README.md): each request decoded strictly, each answer a typed body."""

from __future__ import annotations

import asyncio
import sys
import time

from .api_types import (
    AgentList,
    EmptyRequest,
    ErrorBody,
    Output,
    Restarting,
    SendRequest,
    Sent,
    SessionList,
    StartRequest,
    StopRequest,
)
from .config import HEARTBEAT_SECONDS
from .errors import RunnerError
from .events import Event, Heartbeat
from .http_io import (
    Malformed,
    Request,
    json_line,
    read_request,
    start_stream,
    write_json,
)
from .render import render
from .runner import Runner, status
from .schema import JsonObject, JsonValue, SchemaError, decode, encode

DOCS = "see agents/runner/README.md"


def body_as[T](cls: type[T], req: Request) -> T:
    try:
        return decode(cls, req.body)
    except SchemaError as e:
        raise RunnerError.bad_request(e) from e


def object_body(req: Request) -> JsonObject:
    if not isinstance(req.body, dict):
        raise RunnerError("the body must be a JSON object")
    return req.body


class Api:
    def __init__(self, runner: Runner, stop: asyncio.Event) -> None:
        self.runner = runner
        # Set by POST /v1/restart, after the answer has gone out.
        self.stop = stop
        self.restart_requested = False

    async def handle(
        self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter
    ) -> None:
        try:
            try:
                req = await read_request(reader)
            except Malformed:
                return
            except RunnerError as e:
                write_json(writer, e.status, encode(ErrorBody(str(e))))
                await writer.drain()
                return
            try:
                if await self.stream(req, writer):
                    return
                code, body = await self.route(req)
            except RunnerError as e:
                code, body = e.status, encode(ErrorBody(str(e)))
            except (ConnectionError, BrokenPipeError):
                raise  # the client went away: nobody to answer
            except Exception as e:  # one bad request mustn't end the service
                print(f"agent-runner: {req.method} {req.path}: {e!r}", file=sys.stderr)
                code, body = 500, encode(ErrorBody(f"internal error: {e!r}"))
            write_json(writer, code, body)
            await writer.drain()
        except (ConnectionError, BrokenPipeError):
            pass
        finally:
            writer.close()

    async def route(self, req: Request) -> tuple[int, JsonValue]:
        r = self.runner
        parts = req.parts
        if parts[:1] != ["v1"]:
            raise RunnerError(f"unknown path; {DOCS}", 404)
        match req.method, parts[1:]:
            case "POST", ["restart"]:
                body_as(EmptyRequest, req)
                self.restart_requested = True
                asyncio.get_running_loop().call_later(0.2, self.stop.set)
                return 200, encode(Restarting())
            case "GET", ["agents"]:
                agents = sorted(r.config.agents)
                return 200, encode(AgentList(r.config.default_agent, agents))
            case "GET", ["sessions"]:
                return 200, encode(SessionList(r.summaries()))
            case "POST", ["sessions"]:
                session = await r.start(body_as(StartRequest, req))
                return 201, encode(status(session))
            case "GET", ["sessions", name]:
                return 200, encode(status(r.get(name)))
            case "GET", ["sessions", name, "output"]:
                lines = req.int_param("lines", 40)
                rendered = render(r.get(name).files.read_events())
                return 200, encode(Output(rendered[-lines:] if lines else []))
            case "POST", ["sessions", name, "send"]:
                text = body_as(SendRequest, req).text
                if not text.strip():
                    raise RunnerError("text: the message")
                return 200, encode(Sent(await r.get(name).send(text)))
            case "POST", ["sessions", name, "cancel"]:
                body_as(EmptyRequest, req)
                await r.get(name).cancel()
                return 200, encode(status(r.get(name)))
            case "POST", ["sessions", name, "stop"]:
                reason = body_as(StopRequest, req).reason
                await r.get(name).stop(reason or "stopped")
                return 200, encode(status(r.get(name)))
            case "POST", ["sessions", name, "requests", request_id]:
                r.get(name).answer(request_id, object_body(req))
                return 200, encode(status(r.get(name)))
        raise RunnerError(f"no {req.method} {req.path}; {DOCS}", 404)

    async def stream(self, req: Request, writer: asyncio.StreamWriter) -> bool:
        """GET .../events: the stored events as JSON lines, then live ones with follow=1."""
        parts = req.parts
        if req.method != "GET":
            return False
        if parts == ["v1", "events"]:
            only = None
        elif (
            len(parts) == 4 and parts[:2] == ["v1", "sessions"] and parts[3] == "events"
        ):
            only = parts[2]
        else:
            return False
        session = self.runner.get(only) if only else None
        since = req.int_param("since", 0)
        follow = req.flag("follow")
        start_stream(writer)
        async with self.runner.bus.subscribe() as queue:
            history = (
                list(session.files.read_events(since))
                if session
                else self.runner.bus.recent(since)
            )
            last = since
            for event in history:
                writer.write(json_line(event.encode_json()))
                last = event.seq
            await writer.drain()
            while follow:
                await self.follow(writer, queue, only, last)
        return True

    async def follow(
        self,
        writer: asyncio.StreamWriter,
        queue: asyncio.Queue[Event],
        only: str | None,
        last: int,
    ) -> None:
        """The next live event (one after `last`, of `only` if given), or a heartbeat."""
        try:
            event = await asyncio.wait_for(queue.get(), HEARTBEAT_SECONDS)
        except TimeoutError:
            beat = Heartbeat(ts=time.time(), seq=self.runner.bus.seq)
            writer.write(json_line(encode(beat)))
            await writer.drain()
            return
        if event.seq <= last or (only and event.session != only):
            return
        writer.write(json_line(event.encode_json()))
        await writer.drain()
