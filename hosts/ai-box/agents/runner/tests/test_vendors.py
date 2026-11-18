"""Tests for vendors.py: folder trust, transcripts, and how a model is chosen."""

from __future__ import annotations

import json
import os
import stat
from pathlib import Path
from typing import Any

import pytest
from acp.schema import (
    InitializeResponse,
    NewSessionResponse,
    SetSessionConfigOptionResponse,
    SetSessionConfigOptionSelectRequest,
    SetSessionModelRequest,
    SetSessionModelResponse,
)
from agent_runner import vendors
from agent_runner.errors import RunnerError
from agent_runner.vendors import (
    SteeringResult,
    choose_model,
    steering,
    steers,
    transcript_path,
    trust_folder,
)


def option(config_id: str, category: str | None) -> dict[str, Any]:
    return {
        "id": config_id,
        "name": config_id,
        "category": category,
        "type": "select",
        "currentValue": "x",
        "options": [{"value": "x", "name": "X"}],
    }


def setup(**fields: Any) -> NewSessionResponse:
    return NewSessionResponse.model_validate({"sessionId": "s", **fields})


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


def test_trust_folder_writes_again_if_a_claude_dropped_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    conf = tmp_path / ".claude.json"
    conf.write_text('{"projects": {}}')
    writes: list[str] = []

    def racing(path: Path, text: str) -> None:
        # A claude rewrites the file from its own copy right after the first write.
        writes.append(text)
        path.write_text(text if len(writes) > 1 else '{"projects": {}, "theirs": 1}')

    monkeypatch.setattr(vendors, "write_private", racing)
    trust_folder(conf, "/w")
    assert len(writes) == 2
    assert json.loads(conf.read_text())["projects"]["/w"]["hasTrustDialogAccepted"]


def test_trust_folder_fails_if_the_folder_never_stays_trusted(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    conf = tmp_path / ".claude.json"
    conf.write_text("{}")
    monkeypatch.setattr(vendors, "write_private", lambda path, text: None)
    with pytest.raises(
        ValueError, match="/w doesn't stay trusted in .*: something rewrites"
    ):
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
    choice = choose_model(
        "claude",
        setup(configOptions=[option("mode", "mode"), option("model", "model")]),
        "s",
        "haiku",
    )
    assert choice.method == "session/set_config_option"
    assert choice.params == SetSessionConfigOptionSelectRequest(
        session_id="s", config_id="model", value="haiku"
    )
    assert choice.result is SetSessionConfigOptionResponse


def test_a_boolean_option_is_not_a_model_choice() -> None:
    boolean = {
        "id": "fast",
        "name": "Fast",
        "category": "model",
        "type": "boolean",
        "currentValue": False,
    }
    with pytest.raises(RunnerError, match="offers no model choice"):
        choose_model("x", setup(configOptions=[boolean]), "s", "m")


def test_agy_sets_one_of_its_models() -> None:
    models = {
        "currentModelId": "a",
        "availableModels": [
            {"modelId": "a", "name": "A"},
            {"modelId": "b", "name": "B"},
        ],
    }
    choice = choose_model("antigravity", setup(models=models), "s", "b")
    assert (choice.method, choice.params, choice.result) == (
        "session/set_model",
        SetSessionModelRequest(session_id="s", model_id="b"),
        SetSessionModelResponse,
    )
    with pytest.raises(RunnerError, match="antigravity has no model 'c'; it has: a, b"):
        choose_model("antigravity", setup(models=models), "s", "c")


def test_an_agent_without_a_model_choice() -> None:
    with pytest.raises(RunnerError, match="x offers no model choice over ACP"):
        choose_model("x", setup(configOptions=[option("m", "mode")]), "s", "m")


def test_steering_is_what_initialize_advertises() -> None:
    def init(meta: Any) -> InitializeResponse:
        return InitializeResponse.model_validate({"protocolVersion": 1, "_meta": meta})

    assert steers(init({"steering": {"supported": True}}))
    assert not steers(init({"steering": {"supported": False}}))
    assert not steers(init(None))
    assert not steers(init({"other": 1}))
    assert steering("s", "hi") == {
        "sessionId": "s",
        "prompt": [{"type": "text", "text": "hi"}],
        "_meta": {"steering": {"idleBehavior": "promptRequired"}},
    }
    assert (
        SteeringResult.model_validate({"outcome": "injected", "x": 1}).outcome
        == "injected"
    )
