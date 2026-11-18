"""One agent process: its ACP server as a subprocess, newline-delimited JSON-RPC 2.0 over stdio."""

from __future__ import annotations

import asyncio
import contextlib
import json
import os
import signal
from collections import deque
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

from .acp import RpcId
from .config import LINE_LIMIT, STDERR_TAIL, STOP_GRACE_SECONDS
from .errors import RunnerError
from .schema import JsonObject, JsonValue, Open, SchemaError, alias, decode, encode


class RpcError(Exception):
    """The agent answered a request with an error."""

    def __init__(self, code: int, message: str, data: JsonValue = None) -> None:
        super().__init__(message)
        self.code = code
        self.data = data


class AgentExited(Exception):
    """The agent's process ended while a request to it was open."""


@dataclass(frozen=True)
class ErrorObject(Open):
    code: int = 0
    message: str = "?"
    data: JsonValue = field(default=None, metadata=alias(omit_none=True))


@dataclass(frozen=True, kw_only=True)
class Message(Open):
    """Any JSON-RPC message from the agent: a request, a notification or a response."""

    jsonrpc: Literal["2.0"] = "2.0"
    id: RpcId | None = None
    method: str | None = None
    params: JsonObject | None = None
    result: JsonValue = None
    error: ErrorObject | None = None


@dataclass(frozen=True)
class RequestMessage:
    id: RpcId
    method: str
    params: JsonValue
    jsonrpc: Literal["2.0"] = "2.0"


@dataclass(frozen=True)
class NotificationMessage:
    method: str
    params: JsonValue
    jsonrpc: Literal["2.0"] = "2.0"


@dataclass(frozen=True)
class ResultMessage:
    id: RpcId
    result: JsonValue
    jsonrpc: Literal["2.0"] = "2.0"


@dataclass(frozen=True)
class ErrorMessage:
    id: RpcId
    error: ErrorObject
    jsonrpc: Literal["2.0"] = "2.0"


Outgoing = RequestMessage | NotificationMessage | ResultMessage | ErrorMessage

# A request or notification from the agent: method, params, and the id to answer (None for a
# notification).
Handler = Callable[[str, JsonObject, RpcId | None], Awaitable[None]]


class Connection:
    """An agent's ACP server: requests to it, and its requests and notifications to `on_message`."""

    def __init__(self, proc: asyncio.subprocess.Process, log: Path) -> None:
        self.proc = proc
        self.log = log
        self.next_id = 1
        self.pending: dict[RpcId, asyncio.Future[JsonValue]] = {}
        self.stderr: deque[str] = deque(maxlen=STDERR_TAIL)
        self.on_message: Handler | None = None
        self.closed: asyncio.Future[int] = asyncio.get_running_loop().create_future()
        self.tasks: set[asyncio.Task[None]] = set()

    @classmethod
    async def spawn(
        cls, command: Sequence[str], cwd: str, env: dict[str, str], log: Path
    ) -> Connection:
        try:
            proc = await asyncio.create_subprocess_exec(
                *command,
                cwd=cwd,
                env=env,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                limit=LINE_LIMIT,
                start_new_session=True,
            )
        except OSError as e:
            raise RunnerError(f"can't run {command[0]}: {e}", 500) from e
        conn = cls(proc, log)
        for reader in (conn._read_stdout(), conn._read_stderr()):
            task = asyncio.create_task(reader)
            conn.tasks.add(task)
            task.add_done_callback(conn.tasks.discard)
        return conn

    async def _read_stdout(self) -> None:
        assert self.proc.stdout
        try:
            while line := await self.proc.stdout.readline():
                await self._receive(line)
        finally:
            code = await self.proc.wait()
            for future in self.pending.values():
                if not future.done():
                    future.set_exception(AgentExited(f"the agent exited (code {code})"))
            self.pending.clear()
            if not self.closed.done():
                self.closed.set_result(code)

    async def _receive(self, line: bytes) -> None:
        try:
            msg = decode(Message, json.loads(line))
        except (ValueError, SchemaError) as e:
            self.stderr.append(
                f"(not a JSON-RPC message on stdout: {e}) {line[:200]!r}"
            )
            return
        if msg.method is None:
            future = self.pending.pop(msg.id, None) if msg.id is not None else None
            if future and not future.done():
                if msg.error is not None:
                    err = msg.error
                    future.set_exception(RpcError(err.code, err.message, err.data))
                else:
                    future.set_result(msg.result)
            return
        if self.on_message:
            await self.on_message(msg.method, msg.params or {}, msg.id)

    async def _read_stderr(self) -> None:
        assert self.proc.stderr
        with self.log.open("ab") as log:
            while line := await self.proc.stderr.readline():
                log.write(line)
                log.flush()
                self.stderr.append(line.decode(errors="replace").rstrip())

    def _write(self, msg: Outgoing) -> None:
        if self.proc.stdin is None or self.proc.stdin.is_closing():
            raise AgentExited("the agent's input is closed")
        self.proc.stdin.write(json.dumps(encode(msg)).encode() + b"\n")

    async def call(
        self, method: str, params: object, timeout: float | None = None
    ) -> JsonValue:
        """A request; its result as JSON. RpcError, AgentExited, or RunnerError on a timeout."""
        rid = self.next_id
        self.next_id += 1
        future: asyncio.Future[JsonValue] = asyncio.get_running_loop().create_future()
        self.pending[rid] = future
        self._write(RequestMessage(rid, method, encode(params)))
        try:
            return await asyncio.wait_for(future, timeout)
        except TimeoutError as e:
            self.pending.pop(rid, None)
            raise RunnerError(
                f"the agent didn't answer {method} within {timeout:.0f} s", 504
            ) from e

    async def request[T](
        self, result_type: type[T], method: str, params: object, timeout: float | None
    ) -> T:
        """A request whose result is a `result_type`; one that doesn't fit is an RpcError."""
        result = await self.call(method, params, timeout)
        try:
            return decode(result_type, {} if result is None else result)
        except SchemaError as e:
            raise RpcError(
                0, f"the agent's answer to {method} doesn't fit ACP: {e}"
            ) from e

    def notify(self, method: str, params: object) -> None:
        self._write(NotificationMessage(method, encode(params)))

    def respond(self, rid: RpcId, result: object) -> None:
        with contextlib.suppress(AgentExited):
            self._write(ResultMessage(rid, encode(result)))

    def respond_error(self, rid: RpcId, code: int, message: str) -> None:
        with contextlib.suppress(AgentExited):
            self._write(ErrorMessage(rid, ErrorObject(code, message)))

    @property
    def running(self) -> bool:
        return not self.closed.done()

    def stderr_tail(self, lines: int = 5) -> str:
        return " | ".join(list(self.stderr)[-lines:])

    async def terminate(self) -> None:
        """SIGTERM to the agent's process group; SIGKILL after the grace period."""
        if not self.running:
            return
        with contextlib.suppress(ProcessLookupError):
            os.killpg(self.proc.pid, signal.SIGTERM)
        try:
            await asyncio.wait_for(asyncio.shield(self.closed), STOP_GRACE_SECONDS)
        except TimeoutError:
            with contextlib.suppress(ProcessLookupError):
                os.killpg(self.proc.pid, signal.SIGKILL)
            await self.closed
