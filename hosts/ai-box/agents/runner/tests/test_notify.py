"""Tests for notify.py: telling Alex, and reporting when that fails."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import pytest
from agent_runner.notify import Notifier, Outcome


def send(command: list[str], message: str = "it broke", timeout: float = 10) -> Outcome:
    return asyncio.run(Notifier(command, timeout).send(message))


def test_the_message_is_the_last_argument(tmp_path: Path) -> None:
    out = tmp_path / "out"
    assert send(["sh", "-c", f'printf "%s" "$1" > {out}', "notify"]) == Outcome(True)
    assert out.read_text() == "it broke"


def test_a_failing_command_reports_its_exit_and_stderr() -> None:
    outcome = send(["sh", "-c", "echo no webhook >&2; exit 3"])
    assert outcome == Outcome(False, "exit 3: no webhook")


def test_a_missing_command() -> None:
    outcome = send(["/nonexistent/notify-alex"])
    assert not outcome.ok and "FileNotFoundError" in str(outcome.error)


def test_a_command_that_hangs_is_killed() -> None:
    outcome = send([sys.executable, "-c", "import time; time.sleep(30)"], timeout=0.3)
    assert not outcome.ok and "TimeoutError" in str(outcome.error)


def test_notify_runs_in_the_background_and_reports(
    capsys: pytest.CaptureFixture[str],
) -> None:
    got: list[tuple[str, Outcome]] = []

    async def main() -> None:
        notifier = Notifier(["sh", "-c", "exit 1"])
        notifier.notify("m", lambda message, outcome: got.append((message, outcome)))
        assert got == []
        await asyncio.gather(*notifier.tasks)

    asyncio.run(main())
    assert got == [("m", Outcome(False, "exit 1: "))]
    err = capsys.readouterr().err
    assert "m\n" in err and "notify failed: exit 1" in err


def test_without_a_command_the_message_is_only_printed(
    capsys: pytest.CaptureFixture[str],
) -> None:
    got: list[tuple[str, Outcome]] = []

    async def main() -> None:
        Notifier([]).notify(
            "m", lambda message, outcome: got.append((message, outcome))
        )

    asyncio.run(main())
    assert got == []
    assert capsys.readouterr().err == "m\n"
