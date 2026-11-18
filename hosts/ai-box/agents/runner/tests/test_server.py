"""server.py: the service's settings, and serving until it's told to stop."""

from __future__ import annotations

import asyncio
import json
import stat
from pathlib import Path

import pytest
from agent_runner.client import Client
from agent_runner.config import RESTART_EXIT
from agent_runner.server import SettingMissing, Settings, serve
from conftest import fake_agent
from pydantic import ValidationError

ENV = {
    "AGENT_RUNNER_SOCKET": "/run/s",
    "AGENT_RUNNER_STATE": "/state",
    "AGENT_RUNNER_AGENTS": "/agents.json",
}


def test_settings_from_the_environment() -> None:
    s = Settings.from_env({**ENV, "AGENT_RUNNER_NOTIFY": "notify-alex --quiet"})
    assert s == Settings(
        Path("/run/s"), Path("/state"), Path("/agents.json"), ["notify-alex", "--quiet"]
    )
    assert Settings.from_env(ENV).notify == []


@pytest.mark.parametrize("missing", sorted(ENV))
def test_a_missing_setting(missing: str) -> None:
    env = {k: v for k, v in ENV.items() if k != missing}
    with pytest.raises(SettingMissing, match=f"{missing} isn't set"):
        Settings.from_env(env)
    with pytest.raises(SettingMissing):
        Settings.from_env({**env, missing: ""})


def settings(tmp: Path, agents: object) -> Settings:
    (tmp / "agents.json").write_text(json.dumps(agents))
    return Settings(tmp / "run" / "sock", tmp / "state", tmp / "agents.json", [])


def test_serve_until_stopped(tmp_path: Path) -> None:
    s = settings(tmp_path, {"default": "fake", "agents": {"fake": fake_agent()}})
    s.socket.parent.mkdir()
    s.socket.write_text("a stale socket")

    async def go() -> int:
        stop = asyncio.Event()
        task = asyncio.create_task(serve(s, stop))
        while not s.socket.is_socket():
            await asyncio.sleep(0.02)
        assert stat.S_IMODE(s.socket.stat().st_mode) == 0o600
        agents = await asyncio.to_thread(Client(str(s.socket)).agents)
        assert agents.default == "fake" and agents.agents == ["fake"]
        stop.set()
        return await task

    assert asyncio.run(go()) == 0


def test_restart_exits_for_systemd(tmp_path: Path) -> None:
    s = settings(tmp_path, {"default": "fake", "agents": {"fake": fake_agent()}})

    async def go() -> int:
        task = asyncio.create_task(serve(s, asyncio.Event()))
        while not s.socket.is_socket():
            await asyncio.sleep(0.02)
        restarting = await asyncio.to_thread(Client(str(s.socket)).restart)
        assert restarting.restarting is True
        return await asyncio.wait_for(task, 10)

    assert asyncio.run(go()) == RESTART_EXIT


def test_a_bad_agents_file_stops_the_service(tmp_path: Path) -> None:
    s = settings(tmp_path, {"default": "fake", "agents": {"fake": {"cmd": ["x"]}}})
    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        asyncio.run(serve(s, asyncio.Event()))
    s = settings(tmp_path, {"default": "nobody", "agents": {"fake": fake_agent()}})
    with pytest.raises(ValueError, match="default agent 'nobody' isn't defined"):
        asyncio.run(serve(s, asyncio.Event()))
    assert not s.socket.exists()
