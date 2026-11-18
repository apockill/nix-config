"""Tests for handshake.py: an agent's environment, and opening a session on the stand-in agent."""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

import pytest
from agent_runner.acp import RpcId
from agent_runner.config import AgentSpec
from agent_runner.errors import RunnerError
from agent_runner.handshake import Opened, Wanted, agent_env, handshake
from agent_runner.rpc import Connection
from agent_runner.schema import JsonObject
from conftest import FAKE

BASE = {"PATH": "/bin", "HOME": "/h", "SECRET": "s", "TOKEN": "t", "TZ": "UTC"}


def test_agent_env_takes_little_of_the_runner_and_refuses_billing_keys() -> None:
    spec = AgentSpec(command=["x"], env={"A": "spec", "LANG": "en"}, pass_env=["TOKEN"])
    env = agent_env(
        "x",
        spec,
        {"A": "session", "ANTHROPIC_API_KEY": "k"},
        ["ANTHROPIC_API_KEY"],
        BASE,
    )
    assert env == {
        "PATH": "/bin",
        "HOME": "/h",
        "TZ": "UTC",
        "LANG": "en",
        "A": "session",
        "TOKEN": "t",
    }


def test_agent_env_defaults_lang() -> None:
    assert agent_env("x", AgentSpec(command=["x"]), {}, [], {})["LANG"] == "C.UTF-8"


def test_a_missing_pass_through_variable_fails() -> None:
    spec = AgentSpec(command=["x"], pass_env=["TOKEN", "OTHER"])
    with pytest.raises(RunnerError, match="the runner has no OTHER for claude") as e:
        agent_env("claude", spec, {}, [], BASE)
    assert e.value.status == 500
    with pytest.raises(RunnerError, match="no TOKEN"):
        agent_env("claude", spec, {}, [], {**BASE, "TOKEN": "", "OTHER": "o"})


class Opening:
    """The stand-in agent, opened with handshake(); what it received is in `log`."""

    def __init__(self, tmp_path: Path, **env: str) -> None:
        self.tmp = tmp_path
        self.log = tmp_path / "fake.log"
        self.env = {"FAKE_LOG": str(self.log), **env}
        self.muted = False
        self.mutes: list[bool] = []
        self.created: list[tuple[str, str | None]] = []
        self.updates: list[tuple[JsonObject, bool]] = []

    def mute(self, on: bool) -> None:
        self.muted = on
        self.mutes.append(on)

    def open(self, wanted: Wanted, spec: AgentSpec | None = None) -> Opened:
        spec = spec or AgentSpec(
            command=[sys.executable, FAKE], transcript="/t/{session_id}"
        )

        async def main() -> Opened:
            conn = await Connection.spawn(
                spec.command, str(self.tmp), self.env, self.tmp / "agent.log"
            )

            async def on_message(
                method: str, params: JsonObject, rid: RpcId | None
            ) -> None:
                self.updates.append((params, self.muted))

            conn.on_message = on_message
            try:
                return await handshake(
                    conn,
                    spec,
                    wanted,
                    self.mute,
                    lambda s, t: self.created.append((s, t)),
                )
            finally:
                await conn.terminate()

        return asyncio.run(main())

    def received(self) -> list[JsonObject]:
        return [json.loads(line) for line in self.log.read_text().splitlines()]

    def methods(self) -> list[str]:
        return [str(m["method"]) for m in self.received() if "method" in m]

    def params(self, index: int) -> JsonObject:
        params = self.received()[index]["params"]
        assert isinstance(params, dict)
        return params


def test_a_new_session(tmp_path: Path) -> None:
    o = Opening(tmp_path)
    meta: JsonObject = {"claudeCode": {"options": {"maxTurns": 3}}}
    spec = AgentSpec(
        command=[sys.executable, FAKE], mode="auto", transcript="/t/{session_id}"
    )
    opened = o.open(Wanted(agent="fake", dir="/w", model="small", meta=meta), spec)
    assert o.methods() == [
        "initialize",
        "session/new",
        "session/set_mode",
        "session/set_model",
    ]
    new, mode, model = o.received()[1:]
    assert new["params"] == {"cwd": "/w", "mcpServers": [], "_meta": meta}
    assert mode["params"] == {"sessionId": opened.session_id, "modeId": "auto"}
    assert model["params"] == {"sessionId": opened.session_id, "modelId": "small"}
    assert opened.transcript == f"/t/{opened.session_id}"
    assert opened.init.agent_info == {"name": "fake", "version": "0"}
    assert o.created == [(opened.session_id, opened.transcript)]
    assert o.mutes == []


def test_the_sessions_own_mode_wins_and_none_is_none(tmp_path: Path) -> None:
    o = Opening(tmp_path)
    o.open(Wanted(agent="fake", dir="/w", mode="plan"))
    assert o.params(-1)["modeId"] == "plan"
    second = tmp_path / "second"
    second.mkdir()
    o2 = Opening(second)
    o2.open(Wanted(agent="fake", dir="/w"))
    assert o2.methods() == ["initialize", "session/new"]
    assert "_meta" not in o2.params(1)


def test_resume(tmp_path: Path) -> None:
    o = Opening(tmp_path)
    opened = o.open(Wanted(agent="fake", dir="/w", resume="old-id"))
    assert opened.session_id == "old-id"
    assert o.methods() == ["initialize", "session/resume"]
    assert o.params(1) == {
        "cwd": "/w",
        "mcpServers": [],
        "sessionId": "old-id",
    }
    assert o.mutes == []


def test_an_agent_that_only_loads_replays_history_muted(tmp_path: Path) -> None:
    o = Opening(tmp_path, FAKE_LOAD_ONLY="1")
    o.open(Wanted(agent="agy", dir="/w", resume="old-id"))
    assert o.methods() == ["initialize", "session/load"]
    assert o.mutes == [True, False]
    [(params, muted)] = o.updates
    assert muted
    assert params["update"] == {
        "sessionUpdate": "agent_message_chunk",
        "content": {"type": "text", "text": "history"},
    }


def test_a_model_as_a_config_option(tmp_path: Path) -> None:
    o = Opening(tmp_path, FAKE_CONFIG_MODEL="1")
    opened = o.open(Wanted(agent="claude", dir="/w", model="haiku"))
    assert o.params(-1) == {
        "sessionId": opened.session_id,
        "configId": "model",
        "value": "haiku",
    }


def test_a_bad_model_fails_after_the_session_is_known(tmp_path: Path) -> None:
    o = Opening(tmp_path)
    with pytest.raises(
        RunnerError, match="fake has no model 'huge'; it has: big, small"
    ):
        o.open(Wanted(agent="fake", dir="/w", model="huge"))
    [(session_id, transcript)] = o.created
    assert session_id and transcript == f"/t/{session_id}"


def test_an_agent_that_cannot_resume(tmp_path: Path) -> None:
    script = tmp_path / "plain.py"
    script.write_text(
        "import json, sys\n"
        "for line in sys.stdin:\n"
        "    m = json.loads(line)\n"
        '    print(json.dumps({"jsonrpc": "2.0", "id": m["id"], "result": {}}), flush=True)\n'
    )
    o = Opening(tmp_path)
    with pytest.raises(RunnerError, match="plain can't resume a session over ACP"):
        o.open(
            Wanted(agent="plain", dir="/w", resume="x"),
            AgentSpec(command=[sys.executable, str(script)]),
        )
