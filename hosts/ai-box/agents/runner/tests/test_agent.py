"""Tests for agent.py: one agent process on the ACP SDK, against the stand-in agent
(fake_acp_agent.py) and small inline agents for what it can't do."""

from __future__ import annotations

import time
from pathlib import Path

import pytest
from acp.exceptions import RequestError
from acp.meta import AGENT_METHODS
from acp.schema import InitializeResponse
from agent_runner import agent as agent_module
from agent_runner.agent import AgentExited, AgentProcess, agent_env
from agent_runner.config import AgentSpec
from agent_runner.errors import RunnerError
from agent_runner.opening import Wanted
from fakes import HELLO, Peer, fake_log, odd, opener, run, until

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
