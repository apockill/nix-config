"""`agent serve`: the service, the API served by uvicorn on the unix socket. Its settings come
from the environment (default.nix sets them):

AGENT_RUNNER_SOCKET  the API's unix socket
AGENT_RUNNER_STATE   the state folder: sessions/<name>/{session.json,events.jsonl,agent.log}
AGENT_RUNNER_AGENTS  the agents file (JSON)
AGENT_RUNNER_NOTIFY  the command that tells Alex when a session fails (message as last argument)
"""

from __future__ import annotations

import asyncio
import contextlib
import os
import signal
import socket
import sys
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

import uvicorn

from .api import Api
from .config import RESTART_EXIT, Config
from .notify import Notifier
from .runner import Runner
from .store import Store


class SettingMissing(Exception):
    pass


@dataclass(frozen=True)
class Settings:
    socket: Path
    state: Path
    agents: Path
    notify: list[str]

    @classmethod
    def from_env(cls, environ: Mapping[str, str]) -> Settings:
        def need(name: str) -> str:
            value = environ.get(name)
            if not value:
                raise SettingMissing(
                    f"{name} isn't set (agents/runner/default.nix sets it)"
                )
            return value

        notify = environ.get("AGENT_RUNNER_NOTIFY", "")
        return cls(
            Path(need("AGENT_RUNNER_SOCKET")),
            Path(need("AGENT_RUNNER_STATE")),
            Path(need("AGENT_RUNNER_AGENTS")),
            notify.split(),
        )


def listen(path: Path) -> socket.socket:
    """The API's socket: the agent's user and group only (uvicorn's own would be 0666)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.unlink(missing_ok=True)
    sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    sock.bind(str(path))
    os.chmod(path, 0o660)
    sock.listen(128)
    return sock


async def serve(settings: Settings, stop: asyncio.Event | None = None) -> int:
    """Serve until SIGTERM/SIGINT (or, given one, until `stop` is set: the tests).

    Returns the exit code: RESTART_EXIT after POST /v1/restart, else 0.
    """
    runner = Runner(
        Config.load(settings.agents), Store(settings.state), Notifier(settings.notify)
    )
    runner.load()
    if stop is None:
        stop = asyncio.Event()
        loop = asyncio.get_running_loop()
        for sig in (signal.SIGTERM, signal.SIGINT):
            loop.add_signal_handler(sig, stop.set)
    api = Api(runner, stop)
    config = uvicorn.Config(
        api.app(), log_level="warning", lifespan="off", access_log=False
    )
    server = uvicorn.Server(config)
    sock = listen(settings.socket)
    print(
        f"agent-runner: serving on {settings.socket}, {len(runner.sessions)} sessions on record",
        file=sys.stderr,
        flush=True,
    )
    serving = asyncio.create_task(server.serve(sockets=[sock]))
    stopped = asyncio.create_task(stop.wait())
    await asyncio.wait({serving, stopped}, return_when=asyncio.FIRST_COMPLETED)
    server.should_exit = True
    # Live event streams end with the service.
    server.force_exit = True
    await serving
    stopped.cancel()
    with contextlib.suppress(OSError):
        sock.close()
    await runner.shutdown()
    return RESTART_EXIT if api.restart_requested else 0
