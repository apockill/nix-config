"""What the tests of agent.py and opening.py share: the runner's side of a connection, and the
stand-in agent as an AgentProcess."""

from __future__ import annotations

import asyncio
import json
import os
import sys
import time
from collections.abc import Awaitable, Callable, Coroutine
from pathlib import Path
from typing import Any

from acp.connection import StreamEvent
from acp.schema import InitializeRequest
from agent_runner.agent import AgentProcess
from agent_runner.config import AgentSpec
from agent_runner.opening import Wanted, open_session
from conftest import FAKE

# Agents that do one odd thing each: argv[1] says which.
ODD = """\
import json, signal, sys, time
how = sys.argv[1]
if how == "stubborn":
    signal.signal(signal.SIGTERM, signal.SIG_IGN)
print("starting up", file=sys.stderr, flush=True)
for line in sys.stdin:
    msg = json.loads(line)
    if how == "silent":
        continue
    if how == "exit":
        print("giving up", file=sys.stderr, flush=True)
        sys.exit(4)
    if how == "misfit":
        result = {"agentInfo": "not an object"}
    elif how == "bare":  # no capabilities: can't resume
        result = {"protocolVersion": 1}
    elif how == "refuse":
        print(json.dumps({"jsonrpc": "2.0", "id": msg["id"],
            "error": {"code": -32000, "message": "Authentication required"}}), flush=True)
        continue
    else:
        result = {"protocolVersion": 1}
    if msg.get("method") == "session/new":
        result = {"sessionId": "s1"}
    print(json.dumps({"jsonrpc": "2.0", "id": msg["id"], "result": result}), flush=True)
    if how == "stubborn":
        time.sleep(60)
"""


class Peer:
    """The runner's side, recording what the agent sent."""

    def __init__(self) -> None:
        self.seen: list[dict[str, Any]] = []
        self.muted: list[bool] = []
        self.created: list[tuple[str, str | None]] = []

    async def handle(self, method: str, params: Any, is_notification: bool) -> Any:
        return None

    def observe(self, event: StreamEvent) -> None:
        if event.direction.value == "incoming" and "method" in event.message:
            self.seen.append(
                {**event.message, "muted": bool(self.muted and self.muted[-1])}
            )

    def mute(self, on: bool) -> None:
        self.muted.append(on)

    def create(self, session_id: str, transcript: str | None) -> None:
        self.created.append((session_id, transcript))


def run(test: Callable[[], Coroutine[Any, Any, None]]) -> None:
    asyncio.run(test())


async def fake(tmp: Path, peer: Peer, **env: str) -> AgentProcess:
    full = {**os.environ, "FAKE_LOG": str(tmp / "fake.log"), **env}
    return await AgentProcess.spawn(
        [sys.executable, FAKE], str(tmp), full, tmp / "agent.log", peer
    )


def fake_log(tmp: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in (tmp / "fake.log").read_text().splitlines()]


HELLO = InitializeRequest(protocol_version=1)
SPEC = AgentSpec(command=["fake"], transcript="/t/{session_id}.jsonl")


async def until(check: Callable[[], bool], timeout: float = 5) -> None:
    deadline = time.monotonic() + timeout
    while not check():
        assert time.monotonic() < deadline, "timed out"
        await asyncio.sleep(0.02)


def opener(
    tmp: Path, peer: Peer, wanted: Wanted, spec: AgentSpec = SPEC, **env: str
) -> Callable[[], Awaitable[tuple[AgentProcess, Any]]]:
    async def go() -> tuple[AgentProcess, Any]:
        agent = await fake(tmp, peer, **env)
        try:
            return agent, await open_session(
                agent, spec, wanted, peer.mute, peer.create
            )
        except BaseException:
            await agent.terminate()
            raise

    return go


async def odd(tmp: Path, how: str, peer: Peer | None = None) -> AgentProcess:
    script = tmp / "odd_agent.py"
    script.write_text(ODD)
    return await AgentProcess.spawn(
        [sys.executable, str(script), how],
        str(tmp),
        dict(os.environ),
        tmp / "agent.log",
        peer or Peer(),
    )
