"""canary.py: what runs without the box's sign-ins; the live checks run as `agents-canary`."""

from __future__ import annotations

from pathlib import Path

import canary
import pytest
from evidence import CanaryError


def test_the_agy_checks_skip_without_a_sign_in(tmp_path: Path) -> None:
    setup = canary.Setup(
        agent="agent",
        instructions=tmp_path / "AGENTS.md",
        secrets=tmp_path / "env",
        pass_env=[],
        home=str(tmp_path),
        agy_token=tmp_path / "missing-token",
        work=tmp_path,
    )
    runner = canary.Runner("agent", tmp_path, {})
    assert [c.line() for c in canary.agy_checks(runner, setup, tmp_path)] == [
        "skip agy: not signed in"
    ]


def test_a_missing_sign_in_stops_the_canary(tmp_path: Path) -> None:
    (tmp_path / "env").write_text("OTHER=1\n")
    setup = canary.Setup("agent", tmp_path, tmp_path / "env", ["CLAUDE_CODE_OAUTH_TOKEN"],
                         str(tmp_path), tmp_path, tmp_path)  # fmt: skip
    with pytest.raises(CanaryError, match="no CLAUDE_CODE_OAUTH_TOKEN"):
        canary.base_env(setup)
