"""jobs.py: names from titles, the start request of a job, and answers."""

from __future__ import annotations

from pathlib import Path

import pytest
from agent_runner.jobs import (
    JobError,
    JobSpec,
    answer_body,
    read_task,
    slug,
    start_request,
)


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
