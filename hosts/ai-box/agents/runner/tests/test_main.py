"""__main__.py: `agent serve` runs the service, every other verb the CLI."""

from __future__ import annotations

import pytest
from agent_runner.__main__ import main
from conftest import Service


def test_serve_takes_no_arguments(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["serve", "--now"]) == 2
    assert "agent: serve takes no arguments" in capsys.readouterr().err


def test_serve_needs_its_settings(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    for name in ("AGENT_RUNNER_SOCKET", "AGENT_RUNNER_STATE", "AGENT_RUNNER_AGENTS"):
        monkeypatch.delenv(name, raising=False)
    assert main(["serve"]) == 1
    assert "AGENT_RUNNER_SOCKET isn't set" in capsys.readouterr().err


def test_other_verbs_are_the_cli(
    service: Service,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setenv("AGENT_RUNNER_SOCKET", str(service.socket))
    monkeypatch.delenv("AGENT_RUNNER_CC_TMUX", raising=False)
    assert main(["list"]) == 0
    assert capsys.readouterr().out == "no sessions\n"
    monkeypatch.delenv("AGENT_RUNNER_SOCKET")
    assert main(["list"]) == 1
    assert "agent: AGENT_RUNNER_SOCKET isn't set" in capsys.readouterr().err
