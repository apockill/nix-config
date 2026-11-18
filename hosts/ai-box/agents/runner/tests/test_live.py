"""Live smoke tests: a real Claude (Haiku) and a real Antigravity (Flash) session on a private
runner. They skip unless AGENT_RUNNER_LIVE_AGENTS names the runner's agents file (the store path
in the `agent` wrapper's AGENT_RUNNER_AGENTS), and each skips without its agent's sign-in:
Claude's token in the environment (its pass_env), agy's token file in ~/.gemini.

  AGENT_RUNNER_LIVE_AGENTS=$(grep -o '/nix/store/[^ ]*agents.json' $(which agent)) \\
    CLAUDE_CODE_OAUTH_TOKEN=... pytest tests/test_live.py
"""

from __future__ import annotations

import json
import os
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from conftest import Service, wait_for

LIVE = os.environ.get("AGENT_RUNNER_LIVE_AGENTS")
CLAUDE_MODEL = os.environ.get("AGENT_RUNNER_LIVE_CLAUDE_MODEL", "haiku")
AGY_MODEL = os.environ.get("AGENT_RUNNER_LIVE_AGY_MODEL", "gemini-3.8-flash-low")
AGY_SIGN_IN = Path.home() / ".gemini/antigravity-cli/antigravity-oauth-token"
TURN_SECONDS = 240.0

pytestmark = pytest.mark.skipif(
    not LIVE, reason="live: set AGENT_RUNNER_LIVE_AGENTS to the runner's agents file"
)


def live_service(tmp_path: Path, agent: str) -> Service:
    assert LIVE
    agents: dict[str, Any] = json.loads(Path(LIVE).read_text())
    spec = agents["agents"].get(agent)
    if spec is None:
        pytest.skip(f"the agents file has no {agent}")
    if missing := [k for k in spec.get("pass_env", []) if not os.environ.get(k)]:
        pytest.skip(f"no sign-in for {agent}: {', '.join(missing)} isn't set")
    # The session's scratch folder isn't marked trusted in the real .claude.json.
    spec.pop("claude_trust_file", None)
    service = Service(
        tmp_path,
        {
            "default": agent,
            "agents": {agent: spec},
            "refused_env": agents.get("refused_env", []),
        },
    )
    service.start()
    return service


@pytest.fixture
def claude(tmp_path: Path) -> Iterator[Service]:
    service = live_service(tmp_path, "claude")
    yield service
    service.stop()


@pytest.fixture
def antigravity(tmp_path: Path) -> Iterator[Service]:
    if not AGY_SIGN_IN.exists():
        pytest.skip(f"no sign-in for antigravity: {AGY_SIGN_IN} is missing")
    service = live_service(tmp_path, "antigravity")
    yield service
    service.stop()


def idle(service: Service, name: str) -> dict[str, Any]:
    result: dict[str, Any] = wait_for(
        lambda: (s := service.status(name))["state"] in ("idle", "failed") and s,
        TURN_SECONDS,
    )
    assert result["state"] == "idle", result["reason"]
    return result


def test_claude_haiku_runs_a_turn_and_takes_a_message(claude: Service) -> None:
    claude.start_session(
        "live-claude",
        "Reply with exactly LIVE-ONE and nothing else.",
        model=CLAUDE_MODEL,
    )
    assert "LIVE-ONE" in idle(claude, "live-claude")["last_message"]
    sent = claude.call(
        "POST",
        "/v1/sessions/live-claude/send",
        {"text": "Reply with exactly LIVE-TWO and nothing else."},
    )
    assert sent == {"delivery": "sent"}
    done = idle(claude, "live-claude")
    assert "LIVE-TWO" in done["last_message"]
    assert done["transcript"] and Path(done["transcript"]).exists()
    assert (
        claude.call("POST", "/v1/sessions/live-claude/stop", {})["state"] == "stopped"
    )


def test_claude_asks_a_question_that_parks_until_answered(claude: Service) -> None:
    claude.start_session(
        "live-question",
        "Use the AskUserQuestion tool once to ask me which colour I prefer, with the options"
        " Red and Blue. Then reply with exactly COLOUR-<my answer in capitals>.",
        model=CLAUDE_MODEL,
    )
    s: dict[str, Any] = wait_for(
        lambda: (s := claude.status("live-question"))["state"] in ("waiting", "failed")
        and s,
        TURN_SECONDS,
    )
    assert s["state"] == "waiting", s["reason"]
    [asked] = s["pending"]
    assert asked["kind"] == "question"
    # The question, then Claude's free-text "Other" field (question_0_custom).
    field = next(iter(asked["schema"]["properties"]))
    claude.call(
        "POST",
        f"/v1/sessions/live-question/requests/{asked['request_id']}",
        {"action": "accept", "content": {field: "Blue"}},
    )
    assert "COLOUR-BLUE" in idle(claude, "live-question")["last_message"]


def test_antigravity_flash_runs_a_turn(antigravity: Service) -> None:
    antigravity.start_session(
        "live-agy", "Reply with exactly LIVE-AGY and nothing else.", model=AGY_MODEL
    )
    assert "LIVE-AGY" in idle(antigravity, "live-agy")["last_message"]
    antigravity.call("POST", "/v1/sessions/live-agy/stop", {})
