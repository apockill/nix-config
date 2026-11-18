"""One agent process: its ACP server as a subprocess, spoken to with the ACP SDK.

The SDK (agent-client-protocol) gives the JSON-RPC connection over the process's stdio
(`acp.connection.Connection`), the protocol's models (`acp.schema`) and the typed calls
(`acp.utils.request_model`). The runner spawns the process itself rather than with the SDK's
`spawn_stdio_transport`, because it needs what that doesn't give: the exact environment (the SDK's
adds inherited variables back, the refused ones among them), its own process group (stop ends the
agent's children too), and the agent's stderr, logged and kept for the reason a session failed.
It doesn't use the SDK's `ClientSideConnection` either: its client router has no route for
`elicitation/create` or `$/cancel_request`, and it hands updates over as models, while the runner
passes the agent's own JSON on unchanged (inbox.py has the runner's side).
"""

from __future__ import annotations

import asyncio
import contextlib
import os
import signal
from collections import deque
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any, Protocol

from acp.connection import Connection, StreamEvent
from acp.meta import AGENT_METHODS as M
from acp.schema import (
    CancelNotification,
    ClientCapabilities,
    ElicitationCapabilities,
    ElicitationFormCapabilities,
    FileSystemCapabilities,
    PromptRequest,
    PromptResponse,
    TextContentBlock,
)
from acp.utils import notify_model, request_model_from_dict
from pydantic import BaseModel, ValidationError

from .base import JsonObject
from .config import (
    LINE_LIMIT,
    SETUP_SECONDS,
    STDERR_TAIL,
    STOP_GRACE_SECONDS,
    AgentSpec,
)
from .errors import RunnerError

AUTH_REQUIRED = -32000
# What an agent gets of the runner's own environment, before its agent's and session's.
BASE_ENV = ("PATH", "HOME", "USER", "LANG", "TMPDIR", "TZ")

CAPABILITIES = ClientCapabilities(
    fs=FileSystemCapabilities(read_text_file=False, write_text_file=False),
    terminal=False,
    # AskUserQuestion reaches the runner as a form (README.md, "Questions").
    elicitation=ElicitationCapabilities(form=ElicitationFormCapabilities()),
)


class AgentExited(Exception):
    """The agent's process ended while a request to it was open."""


class Peer(Protocol):
    """The runner's side of the connection: what the agent sends (inbox.py)."""

    async def handle(self, method: str, params: Any, is_notification: bool) -> Any: ...

    def observe(self, event: StreamEvent) -> None: ...


def agent_env(
    agent: str,
    spec: AgentSpec,
    session_env: Mapping[str, str],
    refused: Sequence[str],
    base: Mapping[str, str],
) -> dict[str, str]:
    """The agent process's environment; RunnerError if a variable it must get is missing."""
    env = {k: base[k] for k in BASE_ENV if k in base}
    env.setdefault("LANG", "C.UTF-8")
    env.update(spec.env)
    if missing := [k for k in spec.pass_env if not base.get(k)]:
        # Without it the agent might find some other sign-in; no fallbacks.
        raise RunnerError(f"the runner has no {', '.join(missing)} for {agent}", 500)
    env.update({k: base[k] for k in spec.pass_env})
    env.update(session_env)
    for name in refused:
        env.pop(name, None)
    return env


class AgentProcess:
    def __init__(self, proc: asyncio.subprocess.Process, log: Path, peer: Peer) -> None:
        assert proc.stdin and proc.stdout
        self.proc = proc
        self.log = log
        self.stderr: deque[str] = deque(maxlen=STDERR_TAIL)
        self.closed: asyncio.Future[int] = asyncio.get_running_loop().create_future()
        self.conn = Connection(
            peer.handle, proc.stdin, proc.stdout, observers=[peer.observe]
        )
        self.tasks = {
            asyncio.create_task(self._read_stderr()),
            asyncio.create_task(self._wait()),
        }

    @classmethod
    async def spawn(
        cls,
        command: Sequence[str],
        cwd: str,
        env: dict[str, str],
        log: Path,
        peer: Peer,
        umask: int | None = None,
    ) -> AgentProcess:
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
                umask=-1 if umask is None else umask,
            )
        except OSError as e:
            raise RunnerError(f"can't run {command[0]}: {e}", 500) from e
        return cls(proc, log, peer)

    async def _read_stderr(self) -> None:
        assert self.proc.stderr
        with self.log.open("ab") as log:
            while line := await self.proc.stderr.readline():
                log.write(line)
                log.flush()
                self.stderr.append(line.decode(errors="replace").rstrip())

    async def _wait(self) -> None:
        self.closed.set_result(await self.proc.wait())

    async def exit_known(self) -> None:
        """Wait (briefly) for the exit status of an agent whose output just ended, so the session
        has seen it (its watcher, waiting on `closed` from the start, goes first)."""
        with contextlib.suppress(TimeoutError):
            await asyncio.wait_for(asyncio.shield(self.closed), STOP_GRACE_SECONDS)

    @property
    def pid(self) -> int:
        return self.proc.pid

    @property
    def running(self) -> bool:
        return not self.closed.done()

    def stderr_tail(self, lines: int = 5) -> str:
        return " | ".join(list(self.stderr)[-lines:])

    async def call[M: BaseModel](
        self, method: str, params: BaseModel, result: type[M], timeout: float | None
    ) -> M:
        """A request; RequestError from the agent, AgentExited, or RunnerError (timeout, odd answer)."""
        try:
            return await asyncio.wait_for(
                request_model_from_dict(self.conn, method, params, result), timeout
            )
        except TimeoutError as e:
            raise RunnerError(
                f"the agent didn't answer {method} within {timeout:.0f} s", 504
            ) from e
        except ConnectionError as e:
            await self.exit_known()
            raise AgentExited("the agent exited") from e
        except ValidationError as e:
            raise RunnerError(
                f"the agent's answer to {method} doesn't fit ACP: {e}", 502
            ) from e

    async def setup[M: BaseModel](
        self, method: str, params: BaseModel, result: type[M]
    ) -> M:
        """A request of opening a session: each may take SETUP_SECONDS."""
        return await self.call(method, params, result, SETUP_SECONDS)

    async def extension(self, method: str, params: JsonObject, timeout: float) -> Any:
        """A vendor's own request (`_<method>`), raw JSON both ways."""
        try:
            return await asyncio.wait_for(
                self.conn.send_request(method, params), timeout
            )
        except ConnectionError as e:
            await self.exit_known()
            raise AgentExited("the agent exited") from e

    async def prompt(self, session_id: str, text: str) -> PromptResponse:
        params = PromptRequest(
            session_id=session_id, prompt=[TextContentBlock(type="text", text=text)]
        )
        return await self.call(M["session_prompt"], params, PromptResponse, None)

    async def cancel(self, session_id: str) -> None:
        with contextlib.suppress(ConnectionError):
            await notify_model(
                self.conn,
                M["session_cancel"],
                CancelNotification(session_id=session_id),
            )

    async def terminate(self) -> None:
        """SIGTERM to the agent's process group; SIGKILL after the grace period."""
        if self.running:
            with contextlib.suppress(ProcessLookupError):
                os.killpg(self.proc.pid, signal.SIGTERM)
            try:
                await asyncio.wait_for(asyncio.shield(self.closed), STOP_GRACE_SECONDS)
            except TimeoutError:
                with contextlib.suppress(ProcessLookupError):
                    os.killpg(self.proc.pid, signal.SIGKILL)
                await self.closed
        await self.conn.close()
