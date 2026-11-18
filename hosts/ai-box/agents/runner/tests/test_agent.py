"""Tests for agent.py: one agent process on the ACP SDK, against the stand-in agent
(fake_acp_agent.py) and small inline agents for what it can't do."""

from __future__ import annotations

import asyncio
import json
import os
import sys
import time
from collections.abc import Awaitable, Callable, Coroutine
from pathlib import Path
from typing import Any

import pytest
from acp.connection import StreamEvent
from acp.exceptions import RequestError
from acp.meta import AGENT_METHODS
from acp.schema import InitializeRequest, InitializeResponse
from agent_runner import agent as agent_module
from agent_runner.agent import (
    AgentExited,
    AgentProcess,
    Wanted,
    agent_env,
    open_session,
)
from agent_runner.config import AgentSpec
from agent_runner.errors import RunnerError
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


# --- The environment ---------------------------------------------------------------------------


def test_agent_env() -> None:
    spec = AgentSpec(command=["a"], env={"A": "spec", "B": "spec"}, pass_env=["TOKEN"])
    base = {
        "PATH": "/bin",
        "HOME": "/h",
        "SECRET": "x",
        "TOKEN": "t",
        "ANTHROPIC_API_KEY": "k",
    }
    env = agent_env(
        "a",
        spec,
        {"B": "session", "ANTHROPIC_API_KEY": "k"},
        ["ANTHROPIC_API_KEY"],
        base,
    )
    assert env == {
        "PATH": "/bin",
        "HOME": "/h",
        "LANG": "C.UTF-8",
        "A": "spec",
        "B": "session",
        "TOKEN": "t",
    }
    assert (
        agent_env("a", AgentSpec(command=["a"]), {}, [], {"LANG": "de_DE"})["LANG"]
        == "de_DE"
    )
    with pytest.raises(RunnerError, match="the runner has no TOKEN for a") as e:
        agent_env("a", spec, {}, [], {"TOKEN": ""})
    assert e.value.status == 500


# --- The process ---------------------------------------------------------------------------------


def test_a_command_that_does_not_run_is_a_500(tmp_path: Path) -> None:
    async def test() -> None:
        with pytest.raises(RunnerError, match="can't run /nonexistent/agent") as e:
            await AgentProcess.spawn(
                ["/nonexistent/agent"], str(tmp_path), {}, tmp_path / "log", Peer()
            )
        assert e.value.status == 500

    run(test)


def test_a_request_the_agent_does_not_answer_is_a_504(tmp_path: Path) -> None:
    async def test() -> None:
        agent = await odd(tmp_path, "silent")
        with pytest.raises(
            RunnerError, match="didn't answer initialize within 0 s"
        ) as e:
            await agent.call(
                AGENT_METHODS["initialize"], HELLO, InitializeResponse, 0.2
            )
        assert e.value.status == 504
        await agent.terminate()

    run(test)


def test_an_answer_that_does_not_fit_acp_is_a_502(tmp_path: Path) -> None:
    async def test() -> None:
        agent = await odd(tmp_path, "misfit")
        with pytest.raises(
            RunnerError, match="answer to initialize doesn't fit ACP"
        ) as e:
            await agent.call(AGENT_METHODS["initialize"], HELLO, InitializeResponse, 5)
        assert e.value.status == 502
        await agent.terminate()

    run(test)


def test_an_error_from_the_agent_is_a_request_error(tmp_path: Path) -> None:
    async def test() -> None:
        agent = await odd(tmp_path, "refuse")
        with pytest.raises(RequestError) as e:
            await agent.call(AGENT_METHODS["initialize"], HELLO, InitializeResponse, 5)
        assert e.value.code == agent_module.AUTH_REQUIRED
        await agent.terminate()

    run(test)


def test_an_agent_that_exits_mid_request(tmp_path: Path) -> None:
    async def test() -> None:
        agent = await odd(tmp_path, "exit")
        with pytest.raises(AgentExited):
            await agent.call(AGENT_METHODS["initialize"], HELLO, InitializeResponse, 5)
        # The exit is known by the time the call fails: a session's watcher has seen it.
        assert agent.closed.done() and agent.closed.result() == 4
        assert not agent.running
        await until(lambda: "giving up" in agent.stderr_tail())
        assert agent.stderr_tail() == "starting up | giving up"
        assert (tmp_path / "agent.log").read_text() == "starting up\ngiving up\n"
        with pytest.raises(AgentExited):
            await agent.extension("_x/y", {}, 5)
        await agent.cancel("s1")  # nobody to tell: no error
        await agent.terminate()

    run(test)


def test_terminate_kills_an_agent_that_ignores_sigterm(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(agent_module, "STOP_GRACE_SECONDS", 0.3)

    async def test() -> None:
        agent = await odd(tmp_path, "stubborn")
        await agent.call(AGENT_METHODS["initialize"], HELLO, InitializeResponse, 5)
        started = time.monotonic()
        await agent.terminate()
        assert agent.closed.result() == -9
        assert time.monotonic() - started < 5
        await agent.terminate()  # again: nothing to do

    run(test)


# --- Opening a session ---------------------------------------------------------------------------


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


def test_a_new_session_with_mode_and_model(tmp_path: Path) -> None:
    async def test() -> None:
        peer = Peer()
        spec = AgentSpec(
            command=["fake"], mode="auto", transcript="/t/{session_id}.jsonl"
        )
        wanted = Wanted(agent="fake", dir=str(tmp_path), model="small", meta={"x": 1})
        agent, opened = await opener(tmp_path, peer, wanted, spec)()
        sid = opened.session_id
        assert opened.transcript == f"/t/{sid}.jsonl"
        assert peer.created == [(sid, f"/t/{sid}.jsonl")]
        assert opened.init.agent_info.name == "fake"
        log = fake_log(tmp_path)
        assert [m["method"] for m in log] == [
            "initialize",
            "session/new",
            "session/set_mode",
            "session/set_model",
        ]
        init = log[0]["params"]
        assert init["protocolVersion"] == 1
        assert init["clientInfo"] == {"name": "ai-box agent-runner", "version": "1"}
        # The client offers form elicitation, so Claude keeps AskUserQuestion.
        assert init["clientCapabilities"]["elicitation"] == {"form": {}}
        assert log[1]["params"] == {
            "cwd": str(tmp_path),
            "mcpServers": [],
            "_meta": {"x": 1},
        }
        assert log[2]["params"] == {"sessionId": sid, "modeId": "auto"}
        assert log[3]["params"] == {"sessionId": sid, "modelId": "small"}
        await agent.terminate()

    run(test)


def test_a_model_as_a_config_option(tmp_path: Path) -> None:
    async def test() -> None:
        wanted = Wanted(agent="fake", dir=str(tmp_path), model="small")
        agent, opened = await opener(tmp_path, Peer(), wanted, FAKE_CONFIG_MODEL="1")()
        last = fake_log(tmp_path)[-1]
        assert last["method"] == "session/set_config_option"
        assert last["params"] == {
            "sessionId": opened.session_id,
            "configId": "model",
            "value": "small",
        }
        await agent.terminate()

    run(test)


def test_a_model_the_agent_lacks_fails_after_the_session_is_known(
    tmp_path: Path,
) -> None:
    async def test() -> None:
        peer = Peer()
        wanted = Wanted(agent="fake", dir=str(tmp_path), model="huge")
        with pytest.raises(
            RunnerError, match="fake has no model 'huge'; it has: big, small"
        ):
            await opener(tmp_path, peer, wanted)()
        # ...so the failed session can still be resumed.
        [(sid, _)] = peer.created
        assert sid

    run(test)


def test_resume(tmp_path: Path) -> None:
    async def test() -> None:
        peer = Peer()
        wanted = Wanted(agent="fake", dir=str(tmp_path), resume="old-id")
        agent, opened = await opener(tmp_path, peer, wanted)()
        assert opened.session_id == "old-id"
        resume = fake_log(tmp_path)[1]
        assert resume["method"] == "session/resume"
        assert resume["params"] == {
            "cwd": str(tmp_path),
            "sessionId": "old-id",
            "mcpServers": [],
        }
        assert peer.muted == []
        await agent.terminate()

    run(test)


def test_load_replays_history_muted(tmp_path: Path) -> None:
    async def test() -> None:
        peer = Peer()
        wanted = Wanted(agent="fake", dir=str(tmp_path), resume="old-id")
        agent, opened = await opener(tmp_path, peer, wanted, FAKE_LOAD_ONLY="1")()
        assert fake_log(tmp_path)[1]["method"] == "session/load"
        assert peer.muted == [True, False]
        [history] = [m for m in peer.seen if m["method"] == "session/update"]
        assert history["muted"] is True
        assert history["params"]["update"]["content"]["text"] == "history"
        await agent.terminate()

    run(test)


def test_an_agent_that_cannot_resume(tmp_path: Path) -> None:
    async def test() -> None:
        agent = await odd(tmp_path, "bare")
        wanted = Wanted(agent="odd", dir=str(tmp_path), resume="old-id")
        peer = Peer()
        with pytest.raises(RunnerError, match="odd can't resume a session over ACP"):
            await open_session(agent, SPEC, wanted, peer.mute, peer.create)
        assert peer.created == []
        await agent.terminate()

    run(test)


def test_a_prompt_and_the_agents_notifications_in_order(tmp_path: Path) -> None:
    async def test() -> None:
        peer = Peer()
        agent, opened = await opener(
            tmp_path, peer, Wanted(agent="fake", dir=str(tmp_path))
        )()
        result = await agent.prompt(opened.session_id, "hello")
        assert result.stop_reason == "end_turn"
        # The update the agent sent before its answer was seen before the answer came back.
        [update] = [m for m in peer.seen if m["method"] == "session/update"]
        assert update["params"]["update"]["content"]["text"] == "echo: hello"
        prompt = fake_log(tmp_path)[-1]
        assert prompt["params"] == {
            "sessionId": opened.session_id,
            "prompt": [{"type": "text", "text": "hello"}],
        }
        await agent.cancel(opened.session_id)
        await until(lambda: fake_log(tmp_path)[-1]["method"] == "session/cancel")
        await agent.terminate()
        assert not agent.running

    run(test)
