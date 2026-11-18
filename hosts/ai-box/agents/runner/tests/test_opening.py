"""opening.py: opening a session (new, resumed, loaded; its mode and model), against the
stand-in agent."""

from __future__ import annotations

from pathlib import Path

import pytest
from agent_runner.config import AgentSpec
from agent_runner.errors import RunnerError
from agent_runner.opening import Wanted, open_session
from fakes import SPEC, Peer, fake_log, odd, opener, run


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
