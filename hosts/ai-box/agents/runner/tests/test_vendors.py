"""Tests for vendors.py: folder trust, transcripts, and how a model is chosen."""

from __future__ import annotations

import json
import os
import stat
from pathlib import Path

import pytest
from agent_runner.acp import (
    ConfigOption,
    ModelInfo,
    SessionModelState,
    SessionSetup,
    SetConfigOptionParams,
    SetModelParams,
)
from agent_runner.errors import RunnerError
from agent_runner.vendors import choose_model, transcript_path, trust_folder


def test_trust_folder_adds_the_folder_and_keeps_the_rest(tmp_path: Path) -> None:
    conf = tmp_path / ".claude.json"
    conf.write_text(json.dumps({"theme": "dark", "projects": {"/a": {"x": 1}}}))
    trust_folder(conf, "/a")
    trust_folder(conf, "/b")
    data = json.loads(conf.read_text())
    assert data["theme"] == "dark"
    assert data["projects"]["/a"] == {"x": 1, "hasTrustDialogAccepted": True}
    assert data["projects"]["/b"] == {"hasTrustDialogAccepted": True}
    assert stat.S_IMODE(os.stat(conf).st_mode) == 0o600


def test_trust_folder_creates_the_file_and_leaves_a_trusted_one_alone(
    tmp_path: Path,
) -> None:
    conf = tmp_path / ".claude.json"
    trust_folder(conf, "/w")
    assert json.loads(conf.read_text()) == {
        "projects": {"/w": {"hasTrustDialogAccepted": True}}
    }
    before = conf.stat().st_mtime_ns
    trust_folder(conf, "/w")
    assert conf.stat().st_mtime_ns == before


@pytest.mark.parametrize(
    "content", ["[]", '{"projects": []}', '{"projects": {"/w": 1}}']
)
def test_trust_folder_refuses_a_file_it_does_not_understand(
    tmp_path: Path, content: str
) -> None:
    conf = tmp_path / ".claude.json"
    conf.write_text(content)
    with pytest.raises(ValueError):
        trust_folder(conf, "/w")


def test_transcript_path() -> None:
    template = "/c/projects/{cwd_slug}/{session_id}.jsonl"
    assert (
        transcript_path(template, "s1", "/var/lib/x.y")
        == "/c/projects/-var-lib-x-y/s1.jsonl"
    )
    assert transcript_path("{cwd}/{session_id}", "s", "/w") == "/w/s"
    assert transcript_path(None, "s", "/w") is None
    assert transcript_path("", "s", "/w") is None


def test_claude_sets_its_model_as_a_config_option() -> None:
    setup = SessionSetup(
        config_options=[ConfigOption("mode", "mode"), ConfigOption("model", "model")]
    )
    choice = choose_model("claude", setup, "s", "haiku")
    assert choice.method == "session/set_config_option"
    assert choice.params == SetConfigOptionParams("s", "model", "haiku")


def test_agy_sets_one_of_its_models() -> None:
    setup = SessionSetup(models=SessionModelState([ModelInfo("a"), ModelInfo("b")]))
    choice = choose_model("antigravity", setup, "s", "b")
    assert (choice.method, choice.params) == (
        "session/set_model",
        SetModelParams("s", "b"),
    )
    with pytest.raises(RunnerError, match="antigravity has no model 'c'; it has: a, b"):
        choose_model("antigravity", setup, "s", "c")


def test_an_agent_without_a_model_choice() -> None:
    with pytest.raises(RunnerError, match="x offers no model choice over ACP"):
        choose_model(
            "x", SessionSetup(config_options=[ConfigOption("m", "mode")]), "s", "m"
        )
