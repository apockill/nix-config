"""jobs.py: names from titles, the start request of a job, answers, and the tmux jobs' tool."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest
from agent_runner.jobs import (
    JobError,
    JobSpec,
    Legacy,
    answer_body,
    read_task,
    slug,
    start_request,
)

# A stand-in cc-tmux: logs its arguments as one JSON line, then acts on the first one.
FAKE_TMUX = """\
import json, sys
log, known = sys.argv[1], [k for k in sys.argv[2].split(",") if k]
args = sys.argv[3:]
with open(log, "a") as f:
    f.write(json.dumps(args) + "\\n")
if args[0] == "list":
    if known == ["FAIL"]:
        print("tmux is broken", file=sys.stderr)
        sys.exit(1)
    print("\\n".join(f"{k} running since today" for k in known) or "no jobs")
else:
    print(f"tmux {args[0]}")
    sys.exit(3 if args[0] == "stop" else 0)
"""


def fake_tmux(tmp: Path, jobs: list[str]) -> Path:
    """A cc-tmux that knows `jobs`; its calls go to tmp/tmux.log."""
    script = tmp / "fake_tmux.py"
    script.write_text(FAKE_TMUX)
    exe = tmp / "cc-tmux"
    exe.write_text(
        f"#!/bin/sh\nexec {sys.executable} {script} {tmp / 'tmux.log'}"
        f" '{','.join(jobs)}' \"$@\"\n"
    )
    exe.chmod(0o755)
    return exe


def tmux_calls(tmp: Path) -> list[list[str]]:
    log = tmp / "tmux.log"
    if not log.exists():
        return []
    return [json.loads(line) for line in log.read_text().splitlines()]


@pytest.mark.parametrize(
    "title, name",
    [
        ("nix-config: the runner", "nix-config-the-runner"),
        ("  Sites!! Gate speed 2 ", "sites-gate-speed-2"),
        ("x" * 80, "x" * 63),
        ("a" * 62 + " b", "a" * 62),
        ("Ünïcode Straße", "n-code-stra-e"),
        ("!!", ""),
    ],
)
def test_slug(title: str, name: str) -> None:
    assert slug(title) == name


def test_start_request_from_a_task_file(tmp_path: Path) -> None:
    task = tmp_path / "task.md"
    task.write_text("do it\n\n")
    environ = {"PATH": "/the/callers/path", "TMPDIR": "/tmp/x", "HOME": "/home/h"}
    req = start_request(
        JobSpec(
            title="Sites: the thing",
            dir=str(tmp_path),
            task_file=str(task),
            model="opus",
            agent="antigravity",
        ),
        environ,
    )
    assert req.name == "sites-the-thing"
    assert req.dir == str(tmp_path.resolve())
    assert req.task == "do it"
    # Only the passed variables: the caller's tools and temp folder.
    assert req.env == {"PATH": "/the/callers/path", "TMPDIR": "/tmp/x"}
    assert req.origin == "job: Sites: the thing"
    assert (req.model, req.agent) == ("opus", "antigravity")


def test_start_request_options(tmp_path: Path) -> None:
    req = start_request(
        JobSpec(
            title="job",
            dir=str(tmp_path),
            task="inline",
            env=(("PATH", "/mine"), ("X", "1")),
            origin="sculpt: vase",
            resume="abc",
            mode="plan",
            session_meta={"k": 1},
        ),
        {"PATH": "/theirs"},
    )
    assert req.task == "inline"
    assert req.env == {"PATH": "/mine", "X": "1"}
    assert req.origin == "sculpt: vase"
    assert (req.resume, req.mode, req.session_meta) == ("abc", "plan", {"k": 1})
    no_task = start_request(JobSpec(title="job", dir=str(tmp_path)), {})
    assert no_task.task is None and no_task.env == {}


@pytest.mark.parametrize(
    "title, folder, task, error",
    [
        ("!!", ".", None, "needs a letter or digit"),
        ("job", "/nonexistent", None, "isn't a directory"),
        ("job", ".", "/nonexistent", "can't read the task file /nonexistent"),
    ],
)
def test_start_request_refuses(
    title: str, folder: str, task: str | None, error: str
) -> None:
    with pytest.raises(JobError, match=error):
        start_request(JobSpec(title=title, dir=folder, task_file=task), {})


def test_read_task(tmp_path: Path) -> None:
    (tmp_path / "t").write_bytes(b"line one\nline two\n")
    assert read_task(str(tmp_path / "t")) == "line one\nline two"
    with pytest.raises(JobError, match="can't read"):
        read_task(str(tmp_path))


def test_answer_body() -> None:
    assert answer_body("p1", "allow", False, False) == {"option_id": "allow"}
    assert answer_body("p1", None, False, True) == {"cancel": True}
    assert answer_body("q2", '{"question_0": "Blue"}', False, False) == {
        "action": "accept",
        "content": {"question_0": "Blue"},
    }
    assert answer_body("q2", None, True, False) == {"action": "decline"}
    assert answer_body("q2", None, False, True) == {"action": "cancel"}


@pytest.mark.parametrize(
    "request_id, value, decline, error",
    [
        ("p1", None, False, "takes an option id"),
        ("p1", "allow", True, "takes an option id"),
        ("q1", None, False, "form's fields as JSON"),
        ("q1", "{not json", False, "isn't JSON"),
        ("x1", "y", False, "isn't a request id"),
    ],
)
def test_answer_body_refuses(
    request_id: str, value: str | None, decline: bool, error: str
) -> None:
    with pytest.raises(JobError, match=error):
        answer_body(request_id, value, decline, False)


def test_legacy_without_cc_tmux() -> None:
    legacy = Legacy(None)
    assert legacy.listing() == [] and legacy.names() == []


def test_legacy_lists_and_hands_verbs_on(
    tmp_path: Path, capfd: pytest.CaptureFixture[str]
) -> None:
    legacy = Legacy(str(fake_tmux(tmp_path, ["old-job", "other"])))
    assert legacy.listing() == [
        "old-job running since today",
        "other running since today",
    ]
    assert legacy.names() == ["old-job", "other"]
    capfd.readouterr()
    assert legacy.handle(["peek", "old-job", "5"]) == 0
    assert legacy.handle(["stop", "old-job"]) == 3
    assert capfd.readouterr().out == "tmux peek\ntmux stop\n"
    assert tmux_calls(tmp_path)[-2:] == [["peek", "old-job", "5"], ["stop", "old-job"]]


def test_legacy_with_no_jobs(tmp_path: Path) -> None:
    assert Legacy(str(fake_tmux(tmp_path, []))).names() == []


def test_legacy_failures_are_loud(tmp_path: Path) -> None:
    with pytest.raises(JobError, match="cc-tmux list failed: tmux is broken"):
        Legacy(str(fake_tmux(tmp_path, ["FAIL"]))).listing()
    with pytest.raises(JobError, match="can't run /nonexistent/cc-tmux"):
        Legacy("/nonexistent/cc-tmux").listing()
