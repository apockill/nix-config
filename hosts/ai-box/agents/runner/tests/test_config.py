"""Tests for config.py: the agents file."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from agent_runner.config import AgentSpec, Config
from pydantic import ValidationError


def write(tmp_path: Path, data: Any) -> Path:
    path = tmp_path / "agents.json"
    path.write_text(json.dumps(data))
    return path


def test_the_agents_file_as_default_nix_writes_it(tmp_path: Path) -> None:
    config = Config.load(
        write(
            tmp_path,
            {
                "default": "claude",
                "agents": {
                    "claude": {
                        "command": ["claude-agent-acp"],
                        "env": {"CLAUDE_CONFIG_DIR": "/c"},
                        "mode": None,
                        "transcript": "/c/{cwd_slug}/{session_id}.jsonl",
                        "pass_env": ["CLAUDE_CODE_OAUTH_TOKEN"],
                        "claude_trust_file": "/c/.claude.json",
                    },
                    "antigravity": {"command": ["agy", "acp"], "mode": "auto"},
                },
                "refused_env": ["ANTHROPIC_API_KEY"],
            },
        )
    )
    assert config.default_agent == "claude"
    assert config.refused_env == ["ANTHROPIC_API_KEY"]
    assert config.agents["antigravity"] == AgentSpec(
        command=["agy", "acp"], mode="auto"
    )
    assert config.agents["claude"].pass_env == ["CLAUDE_CODE_OAUTH_TOKEN"]


@pytest.mark.parametrize(
    "data, error",
    [
        ({"default": "x", "agents": {"x": {"command": ["a"], "cmd": 1}}}, "cmd"),
        ({"default": "y", "agents": {"x": {"command": ["a"]}}}, "isn't defined"),
        ({"default": "x", "agents": {"x": {"command": []}}}, "at least 1 item"),
        ({"default": "x", "agents": {"x": {"command": "a"}}}, "agents.x.command"),
        ({"default": "x", "agents": {"x": {"command": [1]}}}, "agents.x.command.0"),
        ({"agents": {"x": {"command": ["a"]}}}, "default\n  Field required"),
        ({"default": "x", "agents": {"x": {"command": ["a"]}}, "more": 1}, "more"),
    ],
)
def test_a_file_that_does_not_fit_stops_the_service(
    tmp_path: Path, data: Any, error: str
) -> None:
    with pytest.raises(ValidationError, match=error):
        Config.load(write(tmp_path, data))


def test_refused_env_is_optional(tmp_path: Path) -> None:
    config = Config.load(
        write(tmp_path, {"default": "x", "agents": {"x": {"command": ["a"]}}})
    )
    assert config.refused_env == []
