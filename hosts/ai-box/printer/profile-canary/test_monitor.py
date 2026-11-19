"""Tests for monitor.py."""

from __future__ import annotations

import os
import time
from pathlib import Path

import monitor
import pytest


def run(
    capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch, summary: Path
) -> str:
    monkeypatch.setattr(monitor, "SUMMARY", summary)
    monitor.main()
    return capsys.readouterr().out


def test_prints_the_summary(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / "summary.txt").write_text("OK: nothing newer.\n")
    assert run(capsys, monkeypatch, tmp_path / "summary.txt") == "OK: nothing newer.\n"


def test_a_missing_or_stale_summary_is_a_problem(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    assert run(capsys, monkeypatch, tmp_path / "summary.txt").startswith(
        "PROBLEM: no profile"
    )
    s = tmp_path / "summary.txt"
    s.write_text("OK\n")
    old = time.time() - monitor.STALE_SECONDS - 60
    os.utime(s, (old, old))
    assert run(capsys, monkeypatch, s).startswith(
        "PROBLEM: the profile canary's summary is stale"
    )
