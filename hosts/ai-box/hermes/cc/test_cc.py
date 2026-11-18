"""Tests for cc.py, against stand-ins for agent-runner and cc-tmux. Run with `just test`."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import cc
import pytest

# A stand-in CLI: logs its arguments as one JSON line, then acts on the first one.
FAKE = """\
import json, sys
log, known = sys.argv[1], sys.argv[2].split(",")
args = sys.argv[3:]
with open(log, "a") as f:
    f.write(json.dumps(args) + "\\n")
verb = args[0]
if verb == "list":
    print("\\n".join(f"{k} running since today" for k in known if k) or "no jobs")
elif verb == "status":
    sys.exit(0 if args[1] in known else 1)
elif len(args) > 1 and args[1] not in known and verb in ("send", "peek", "stop"):
    print(f"no session named {args[1]}", file=sys.stderr)
    sys.exit(1)
else:
    print(f"ok {verb}")
"""


class Tools:
    def __init__(
        self, tmp: Path, runner_jobs: list[str], legacy_jobs: list[str]
    ) -> None:
        self.tmp = tmp
        script = tmp / "fake.py"
        script.write_text(FAKE)
        self.env = {"PATH": "/the/callers/path", "TMPDIR": "/tmp/x", "HOME": "/home/h"}
        for name, jobs in (("runner", runner_jobs), ("legacy", legacy_jobs)):
            exe = tmp / name
            exe.write_text(
                f"#!/bin/sh\nexec {sys.executable} {script} {tmp / (name + '.log')} '{','.join(jobs)}' \"$@\"\n"
            )
            exe.chmod(0o755)
        self.env["CC_RUNNER"] = str(tmp / "runner")
        self.env["CC_LEGACY"] = str(tmp / "legacy")

    def calls(self, name: str) -> list[list[str]]:
        log = self.tmp / f"{name}.log"
        return (
            [json.loads(line) for line in log.read_text().splitlines()]
            if log.exists()
            else []
        )

    def cc(self, *argv: str) -> int:
        return cc.main(list(argv), self.env)


@pytest.mark.parametrize(
    "title, session",
    [
        ("nix-config: the runner", "nix-config-the-runner"),
        ("  Sites!! Gate speed 2 ", "sites-gate-speed-2"),
        ("x" * 80, "x" * 63),
    ],
)
def test_slug(title: str, session: str) -> None:
    assert cc.slug(title) == session


def test_start_runs_the_job_on_the_runner(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    tools = Tools(tmp_path, [], [])
    task = tmp_path / "task.md"
    task.write_text("do it\n")
    assert (
        tools.cc(
            "start", "Sites: the thing", str(tmp_path), str(task), "--model", "opus"
        )
        == 0
    )
    assert capsys.readouterr().out.splitlines()[0] == "session: sites-the-thing"
    [call] = [c for c in tools.calls("runner") if c[0] == "start"]
    assert call == [
        "start",
        "sites-the-thing",
        "--dir",
        str(tmp_path),
        "--task-file",
        str(task),
        "--origin",
        "cc: Sites: the thing",
        "--env",
        "PATH=/the/callers/path",
        "--env",
        "TMPDIR=/tmp/x",
        "--model",
        "opus",
    ]


def test_start_with_antigravity(tmp_path: Path) -> None:
    tools = Tools(tmp_path, [], [])
    task = tmp_path / "task.md"
    task.write_text("x")
    assert (
        tools.cc("start", "job", str(tmp_path), str(task), "--agent", "antigravity")
        == 0
    )
    assert tools.calls("runner")[-1][-2:] == ["--agent", "antigravity"]


@pytest.mark.parametrize(
    "argv, error",
    [
        (["start", "!!", ".", "t"], "needs a letter or digit"),
        (["start", "job", "/nonexistent", "t"], "isn't a directory"),
        (["start", "job", ".", "/nonexistent"], "can't read the task file"),
    ],
)
def test_start_refuses(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], argv: list[str], error: str
) -> None:
    tools = Tools(tmp_path, [], [])
    assert tools.cc(*argv) == 1
    assert error in capsys.readouterr().err
    assert not [c for c in tools.calls("runner") if c[0] == "start"]


def test_a_title_still_running_in_tmux_isnt_started_again(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    tools = Tools(tmp_path, [], ["old-job"])
    task = tmp_path / "t"
    task.write_text("x")
    assert tools.cc("start", "Old job", str(tmp_path), str(task)) == 1
    assert "still running in tmux" in capsys.readouterr().err


def test_verbs_go_to_the_runner_or_the_old_tmux_server(tmp_path: Path) -> None:
    tools = Tools(tmp_path, ["new-job"], ["old-job"])
    assert tools.cc("send", "new-job", "hello", "--there") == 0
    assert tools.cc("peek", "old-job", "5") == 0
    assert tools.cc("stop", "old-job") == 0
    assert tools.cc("stop", "new-job") == 0
    runner = [c for c in tools.calls("runner") if c[0] != "status"]
    legacy = [c for c in tools.calls("legacy") if c[0] != "list"]
    assert runner == [["send", "new-job", "hello --there"], ["stop", "new-job"]]
    assert legacy == [["peek", "old-job", "5"], ["stop", "old-job"]]


def test_an_unknown_job_is_the_runners_error(tmp_path: Path) -> None:
    tools = Tools(tmp_path, [], [])
    assert tools.cc("peek", "ghost") == 1
    assert tools.calls("runner")[-1] == ["peek", "ghost", "40"]


def test_answer(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    tools = Tools(tmp_path, ["j"], [])
    assert tools.cc("answer", "j", "p1", "allow") == 0
    assert tools.cc("answer", "j", "q2", '{"question_0": "Blue"}') == 0
    assert tools.calls("runner") == [
        ["answer-permission", "j", "p1", "allow"],
        ["answer-question", "j", "q2", "--json", '{"question_0": "Blue"}'],
    ]
    assert tools.cc("answer", "j", "x1", "y") == 1
    assert "isn't a request id" in capsys.readouterr().err


def test_list_shows_both(tmp_path: Path, capfd: pytest.CaptureFixture[str]) -> None:
    tools = Tools(tmp_path, ["new-job"], ["old-job"])
    assert tools.cc("list") == 0
    assert capfd.readouterr().out.splitlines() == [
        "new-job running since today",
        "in tmux, from before the runner (Remote Control):",
        "  old-job running since today",
    ]
    tools = Tools(tmp_path, [], [])
    assert tools.cc("list") == 0
    assert capfd.readouterr().out.splitlines() == ["no jobs"]


def test_usage(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as e:
        cc.main(["send", "job"], {})
    assert e.value.code == 2
    assert "cc: send needs a message" in capsys.readouterr().err
