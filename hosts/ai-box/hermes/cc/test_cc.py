"""Tests for cc.py. Run with `just test`."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import time
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path

import cc
import pytest
from cc import Job

URL = "https://claude.ai/code/session_01MjXYtR2rLNfeKXikLS6duk"


@dataclass
class FakeSession:
    cwd: Path
    env: list[str]
    command: list[str]
    screens: list[str] = field(default_factory=list)
    keys: list[str] = field(default_factory=list)

    def screen(self) -> str:
        """The next screen in the list, then the last one forever."""
        return self.screens.pop(0) if len(self.screens) > 1 else self.screens[0]


class FakeTmux(cc.Tmux):
    """A tmux server in memory: sessions are created, read and killed, nothing runs."""

    def __init__(self) -> None:
        super().__init__("tmux", "fake-sock", {})
        self.up = True
        self.sessions: dict[str, FakeSession] = {}
        self.launched: list[tuple[str, FakeSession]] = []
        # The screen each new session shows.
        self.screens = [f"Remote Control: {URL}\n"]

    def _run(self, *args: str) -> str:
        raise AssertionError(f"real tmux called: {args}")

    def _session(self, session: str) -> FakeSession:
        if not self.up:
            raise cc.TmuxError("no server running on fake-sock")
        if session not in self.sessions:
            raise cc.TmuxError(f"can't find session: {session}")
        return self.sessions[session]

    def server_running(self) -> bool:
        return self.up

    def has_session(self, session: str) -> bool:
        return self.up and session in self.sessions

    def new_session(
        self, session: str, cwd: Path, env: Sequence[str], command: Sequence[str]
    ) -> None:
        assert self.up and session not in self.sessions
        s = FakeSession(cwd, list(env), list(command), list(self.screens))
        self.sessions[session] = s
        self.launched.append((session, s))

    def capture(self, session: str) -> str:
        return self._session(session).screen()

    def send_keys(self, session: str, *keys: str) -> None:
        self._session(session).keys.extend(keys)

    def send_text(self, session: str, text: str) -> None:
        self._session(session).keys.append(f"text:{text}")

    def list_sessions(self, fmt: str) -> str:
        if not self.up:
            raise cc.TmuxError("no server running on fake-sock")
        return "".join(f"{s} running since today\n" for s in self.sessions)

    def kill_session(self, session: str) -> None:
        self._session(session)
        del self.sessions[session]


@pytest.fixture
def env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """CC_JOBS, HOME and a job directory in tmp_path; returns tmp_path."""
    monkeypatch.setenv("CC_TMUX_SOCK", str(tmp_path / "sock"))
    monkeypatch.setenv("CC_JOBS", str(tmp_path / "jobs"))
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.setenv("PATH", "/bin:/usr/bin")
    monkeypatch.setenv("CLAUDE_CODE_OAUTH_TOKEN", "secret")
    monkeypatch.delenv("TMPDIR", raising=False)
    monkeypatch.delenv("LANG", raising=False)
    (tmp_path / "home").mkdir()
    (tmp_path / "work").mkdir()
    (tmp_path / "task.md").write_text("Do the thing;\n\n")
    return tmp_path


@pytest.fixture
def tmux() -> FakeTmux:
    return FakeTmux()


def run(tmux: FakeTmux, *argv: str) -> int:
    return cc.main(list(argv), tmux=tmux, sleep=lambda _: None)


def start(tmux: FakeTmux, env: Path, name: str = "Proj: Fix the Tests!") -> int:
    return run(tmux, "start", name, str(env / "work"), str(env / "task.md"))


def write_job(env: Path, session: str, job: Job) -> Path:
    path = env / "jobs" / f"{session}.json"
    job.save(path)
    return path


# Names


@pytest.mark.parametrize(
    ("name", "session"),
    [
        ("Proj: Fix the Tests!", "proj-fix-the-tests"),
        ("nix-config: cc in Python", "nix-config-cc-in-python"),
        ("  --Already-slugged--  ", "already-slugged"),
        ("Ünïcode: Café", "n-code-caf"),
        ("two\nlines", "two-lines"),
        ("v2.0 release", "v2-0-release"),
    ],
)
def test_slug(name: str, session: str) -> None:
    assert cc.slug(name) == session


def test_tmux_arg_escapes_only_a_trailing_semicolon() -> None:
    assert cc.tmux_arg("a;b") == "a;b"
    assert cc.tmux_arg("done;") == "done\\;"
    assert cc.tmux_arg(";") == "\\;"
    assert cc.tmux_arg("x\\;") == "x\\\\;"


# Job records


def test_job_record_round_trips(tmp_path: Path) -> None:
    job = Job("p: j", "/work", "1234", ["PATH=/bin", "HOME=/home"])
    job.save(tmp_path / "jobs" / "p-j.json")
    assert Job.load(tmp_path / "jobs" / "p-j.json") == job


def test_job_record_reads_the_shell_versions_format(tmp_path: Path) -> None:
    path = tmp_path / "j.json"
    path.write_text(
        '{"name": "a: b", "dir": "/w", "session_id": "id", "env": ["PATH=/bin"]}'
    )
    assert Job.load(path) == Job("a: b", "/w", "id", ["PATH=/bin"])


@pytest.mark.parametrize(
    ("content", "error"),
    [
        ('{"name": "a", "dir": "/w", "env": []}', "missing session_id"),
        (
            '{"name": "a", "dir": "/w", "session_id": "i", "env": [], "x": 1}',
            "unknown x",
        ),
        ('{"name": "a", "dir": 3, "session_id": "i", "env": []}', "dir isn't a string"),
        ('{"name": "a", "dir": "/w", "session_id": "i", "env": [1]}', "env isn't"),
        ("[]", "not a JSON object"),
        ("{", "can't read job record"),
    ],
)
def test_bad_job_record_fails_clearly(tmp_path: Path, content: str, error: str) -> None:
    path = tmp_path / "j.json"
    path.write_text(content)
    with pytest.raises(cc.CcError, match=error):
        Job.load(path)


# start


def test_start_records_the_job_launches_claude_and_prints_both_lines(
    env: Path, tmux: FakeTmux, capsys: pytest.CaptureFixture[str]
) -> None:
    assert start(tmux, env) == 0
    assert capsys.readouterr().out == f"session: proj-fix-the-tests\nurl: {URL}\n"

    job = Job.load(env / "jobs" / "proj-fix-the-tests.json")
    assert job.name == "Proj: Fix the Tests!"
    assert job.dir == str(env / "work")
    assert job.env == [
        "PATH=/bin:/usr/bin",
        f"HOME={env / 'home'}",
        "TMPDIR=/tmp",
        "LANG=C.UTF-8",
    ]
    assert not any("CLAUDE_CODE_OAUTH_TOKEN" in v for v in job.env)

    s = tmux.sessions["proj-fix-the-tests"]
    assert s.cwd == env / "work"
    assert s.env == job.env
    # The task file's trailing newlines are dropped, as $(cat) did.
    assert s.command == [
        "claude",
        "--remote-control",
        "Proj: Fix the Tests!",
        "--session-id",
        job.session_id,
        "Do the thing;",
    ]
    trust = json.loads((env / "home" / ".claude.json").read_text())
    assert trust["projects"][str(env / "work")]["hasTrustDialogAccepted"] is True


def test_start_trusts_in_claude_config_dir(
    env: Path, tmux: FakeTmux, monkeypatch: pytest.MonkeyPatch
) -> None:
    config_dir = env / "home" / ".claude"
    config_dir.mkdir()
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(config_dir))
    assert start(tmux, env) == 0
    trust = json.loads((config_dir / ".claude.json").read_text())
    assert trust["projects"][str(env / "work")]["hasTrustDialogAccepted"] is True
    assert not (env / "home" / ".claude.json").exists()


def test_start_keeps_the_rest_of_claude_json(env: Path, tmux: FakeTmux) -> None:
    conf = env / "home" / ".claude.json"
    conf.write_text('{"theme": "dark", "projects": {"/other": {"x": 1}}}')
    assert start(tmux, env) == 0
    data = json.loads(conf.read_text())
    assert data["theme"] == "dark"
    assert data["projects"]["/other"] == {"x": 1}
    assert conf.stat().st_mode & 0o777 == 0o600


def test_start_waits_for_the_whole_url(
    env: Path, tmux: FakeTmux, capsys: pytest.CaptureFixture[str]
) -> None:
    # The URL appears without its id first, then in pieces.
    tmux.screens = [
        "Starting…\n",
        "Remote Control: https://claude.ai/code/session_\n",
        "Remote Control: https://claude.ai/code/session_01MjXY\n",
        f"Remote Control: {URL}\n",
    ]
    assert start(tmux, env) == 0
    assert capsys.readouterr().out.splitlines()[-1] == f"url: {URL}"


def test_start_fails_clearly_when_the_url_never_appears_whole(
    env: Path, tmux: FakeTmux, capsys: pytest.CaptureFixture[str]
) -> None:
    tmux.screens = ["Remote Control: https://claude.ai/code/session_\n"]
    slept: list[float] = []
    code = cc.main(
        ["start", "p: j", str(env / "work"), str(env / "task.md")],
        tmux=tmux,
        sleep=slept.append,
    )
    out, err = capsys.readouterr()
    assert code == 1
    assert out == "session: p-j\n"
    assert err == "cc: no Remote Control URL after 30 s; check with: cc peek p-j\n"
    assert sum(slept) == pytest.approx(cc.URL_TIMEOUT_SECONDS)
    # The job keeps running and stays recorded, for a look with cc peek.
    assert "p-j" in tmux.sessions
    assert (env / "jobs" / "p-j.json").exists()


def test_start_refuses_a_running_name(
    env: Path, tmux: FakeTmux, capsys: pytest.CaptureFixture[str]
) -> None:
    assert start(tmux, env) == 0
    record = (env / "jobs" / "proj-fix-the-tests.json").read_text()
    capsys.readouterr()
    assert start(tmux, env) == 1
    assert capsys.readouterr().err == (
        "cc: a job named proj-fix-the-tests is already running\n"
    )
    assert (env / "jobs" / "proj-fix-the-tests.json").read_text() == record


@pytest.mark.parametrize(
    ("args", "error"),
    [
        (["p: j", "missing", "task.md"], "cc: missing isn't a directory\n"),
        (["p: j", "work", "missing.md"], "cc: can't read the task file: "),
        (["!!!", "work", "task.md"], "cc: the name '!!!' needs a letter or digit\n"),
    ],
)
def test_start_errors(
    env: Path,
    tmux: FakeTmux,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    args: list[str],
    error: str,
) -> None:
    monkeypatch.chdir(env)
    assert run(tmux, "start", *args) == 1
    assert capsys.readouterr().err.startswith(error)
    assert tmux.sessions == {}
    assert not (env / "jobs").exists()


def test_start_without_the_tmux_server_fails_clearly(
    env: Path, tmux: FakeTmux, capsys: pytest.CaptureFixture[str]
) -> None:
    tmux.up = False
    assert start(tmux, env) == 1
    assert "tmux server (fake-sock) isn't running" in capsys.readouterr().err
    assert not (env / "jobs").exists()


def test_start_with_an_unwritable_jobs_dir_fails_clearly(
    env: Path, tmux: FakeTmux, capsys: pytest.CaptureFixture[str]
) -> None:
    (env / "jobs").write_text("a file, not a directory")
    assert start(tmux, env) == 1
    assert "cc: can't write job record" in capsys.readouterr().err
    assert tmux.sessions == {}


class BrokenTmux(FakeTmux):
    def new_session(
        self, session: str, cwd: Path, env: Sequence[str], command: Sequence[str]
    ) -> None:
        raise cc.TmuxError("create window failed: fork failed")


def test_start_drops_the_record_when_launching_fails(
    env: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert start(BrokenTmux(), env) == 1
    assert capsys.readouterr().err == "create window failed: fork failed\n"
    assert list((env / "jobs").iterdir()) == []


# send, peek, list


def test_send_types_one_line_then_enter(env: Path, tmux: FakeTmux) -> None:
    start(tmux, env)
    assert run(tmux, "send", "proj-fix-the-tests", "-v", "first\nsecond") == 0
    assert tmux.sessions["proj-fix-the-tests"].keys == [
        "C-u",
        "text:-v first second",
        "Enter",
    ]


def test_send_and_stop_report_an_unknown_session(
    env: Path, tmux: FakeTmux, capsys: pytest.CaptureFixture[str]
) -> None:
    assert run(tmux, "send", "nope", "hi") == 1
    assert run(tmux, "peek", "nope") == 1
    assert run(tmux, "stop", "nope") == 1
    assert capsys.readouterr().err == "can't find session: nope\n" * 3


def test_peek_shows_the_last_non_empty_lines(
    env: Path, tmux: FakeTmux, capsys: pytest.CaptureFixture[str]
) -> None:
    tmux.screens = ["one\n\n  \ntwo\nthree\n\n\n"]
    start(tmux, env)
    capsys.readouterr()
    assert run(tmux, "peek", "proj-fix-the-tests", "2") == 0
    assert capsys.readouterr().out == "two\nthree\n"
    assert run(tmux, "peek", "proj-fix-the-tests") == 0
    assert capsys.readouterr().out == "one\ntwo\nthree\n"


def test_peek_of_a_blank_screen_is_empty_not_an_error(
    env: Path, tmux: FakeTmux, capsys: pytest.CaptureFixture[str]
) -> None:
    tmux.sessions["blank"] = FakeSession(env, [], [], ["\n\n"])
    assert run(tmux, "peek", "blank") == 0
    assert capsys.readouterr().out == ""


def test_list_hides_the_placeholder_session(
    env: Path, tmux: FakeTmux, capsys: pytest.CaptureFixture[str]
) -> None:
    tmux.sessions["_keep"] = FakeSession(env, [], [], [""])
    assert run(tmux, "list") == 0
    assert capsys.readouterr().out == "no jobs\n"
    start(tmux, env)
    capsys.readouterr()
    assert run(tmux, "list") == 0
    assert capsys.readouterr().out == "proj-fix-the-tests running since today\n"


def test_list_without_the_server_says_no_jobs(
    env: Path, tmux: FakeTmux, capsys: pytest.CaptureFixture[str]
) -> None:
    tmux.up = False
    assert run(tmux, "list") == 0
    assert capsys.readouterr().out == "no jobs\n"


# stop


def test_stop_ends_the_job_and_deletes_its_record(env: Path, tmux: FakeTmux) -> None:
    start(tmux, env)
    assert run(tmux, "stop", "proj-fix-the-tests") == 0
    assert tmux.sessions == {}
    assert not (env / "jobs" / "proj-fix-the-tests.json").exists()


# restore


def test_restore_resumes_missing_jobs_and_skips_running_ones(
    env: Path, tmux: FakeTmux, capsys: pytest.CaptureFixture[str]
) -> None:
    (env / "other").mkdir()
    write_job(env, "gone", Job("p: gone", str(env / "other"), "id-1", ["PATH=/x"]))
    write_job(env, "alive", Job("p: alive", str(env / "work"), "id-2", []))
    tmux.sessions["alive"] = FakeSession(env / "work", [], ["claude"], [""])

    assert run(tmux, "restore") == 0
    assert capsys.readouterr().out == "restored: gone\n"
    [(session, s)] = tmux.launched
    assert session == "gone"
    assert s.cwd == env / "other"
    assert s.env == ["PATH=/x"]
    assert s.command == ["claude", "--remote-control", "p: gone", "--resume", "id-1"]
    # Records stay until cc stop.
    assert (env / "jobs" / "gone.json").exists()


def test_restore_with_no_records_does_nothing(env: Path, tmux: FakeTmux) -> None:
    tmux.up = False
    assert run(tmux, "restore") == 0


def test_restore_reports_bad_records_and_still_restores_the_rest(
    env: Path, tmux: FakeTmux, capsys: pytest.CaptureFixture[str]
) -> None:
    (env / "jobs").mkdir()
    (env / "jobs" / "a-broken.json").write_text("{")
    write_job(env, "b-moved", Job("p: b", str(env / "deleted"), "id-b", []))
    write_job(env, "c-fine", Job("p: c", str(env / "work"), "id-c", []))

    assert run(tmux, "restore") == 1
    out, err = capsys.readouterr()
    assert out == "restored: c-fine\n"
    assert "cc: not restored: a-broken: can't read job record" in err
    assert f"cc: not restored: b-moved: {env / 'deleted'} isn't a directory" in err
    assert [s for s, _ in tmux.launched] == ["c-fine"]


def test_restore_without_the_tmux_server_fails_clearly(
    env: Path, tmux: FakeTmux, capsys: pytest.CaptureFixture[str]
) -> None:
    write_job(env, "j", Job("p: j", str(env / "work"), "id", []))
    tmux.up = False
    assert run(tmux, "restore") == 1
    assert "isn't running" in capsys.readouterr().err


# Usage


@pytest.mark.parametrize(
    "argv",
    [[], ["bogus"], ["start", "a", "b"], ["send", "s"], ["peek", "s", "x"], ["stop"]],
)
def test_usage_errors_exit_2(
    env: Path, tmux: FakeTmux, capsys: pytest.CaptureFixture[str], argv: list[str]
) -> None:
    with pytest.raises(SystemExit) as exc:
        run(tmux, *argv)
    assert exc.value.code == 2
    assert capsys.readouterr().err.startswith(cc.USAGE)


def test_missing_environment_fails_clearly(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.delenv("CC_TMUX_SOCK", raising=False)
    monkeypatch.delenv("CC_JOBS", raising=False)
    assert cc.main(["list"]) == 1
    assert capsys.readouterr().err == (
        "cc: CC_TMUX_SOCK and CC_JOBS not set (default.nix sets them)\n"
    )


# A real tmux server


FAKE_CLAUDE = """\
#!{python}
import json, os, sys, time
with open({calls!r}, "a") as f:
    f.write(json.dumps({{
        "argv": sys.argv[1:],
        "cwd": os.getcwd(),
        "token": os.environ.get("CLAUDE_CODE_OAUTH_TOKEN"),
    }}) + "\\n")
print("Remote Control: {url}", flush=True)
time.sleep(600)
"""


def wait_for_calls(path: Path, count: int) -> list[dict[str, object]]:
    """The fake claude's recorded runs, once there are `count` of them."""
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        lines = path.read_text().splitlines() if path.exists() else []
        if len(lines) >= count:
            return [json.loads(line) for line in lines]
        time.sleep(0.1)
    raise AssertionError(f"fake claude ran {len(lines)} times, not {count}")


@pytest.mark.skipif(shutil.which("tmux") is None, reason="needs tmux")
def test_a_job_survives_a_tmux_server_restart(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    # A relative socket: tmp_path can be longer than a socket path may be.
    monkeypatch.chdir(tmp_path)
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    calls = tmp_path / "calls.jsonl"
    claude = bin_dir / "claude"
    claude.write_text(
        FAKE_CLAUDE.format(python=sys.executable, calls=str(calls), url=URL)
    )
    claude.chmod(0o755)
    work = tmp_path / "my work;"
    work.mkdir()
    task = tmp_path / "task.md"
    task.write_text("- first line\nends with a semicolon;\n")
    (tmp_path / "home").mkdir()

    server_env = {"PATH": os.environ["PATH"], "HOME": str(tmp_path / "home")}
    monkeypatch.setenv("PATH", f"{bin_dir}:{os.environ['PATH']}")
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.setenv("CC_TMUX_SOCK", "sock")
    monkeypatch.setenv("CC_JOBS", str(tmp_path / "jobs"))
    monkeypatch.setenv("CLAUDE_CODE_OAUTH_TOKEN", "secret")

    def tmux(*args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["tmux", "-S", "sock", *args],
            env=server_env,
            capture_output=True,
            text=True,
        )

    def start_server() -> None:
        # As the cc-tmux service does, without the token in its environment.
        # Retried: a server just killed can still take the connection and exit.
        deadline = time.monotonic() + 10
        while tmux("new-session", "-d", "-s", "_keep", "sleep", "600").returncode:
            assert time.monotonic() < deadline, "the tmux server didn't start"
            time.sleep(0.1)

    start_server()
    try:
        assert cc.main(["start", "Test: survive", str(work), str(task)]) == 0
        assert capsys.readouterr().out == f"session: test-survive\nurl: {URL}\n"
        [first] = wait_for_calls(calls, 1)
        session_id = Job.load(tmp_path / "jobs" / "test-survive.json").session_id
        assert first == {
            "argv": [
                "--remote-control",
                "Test: survive",
                "--session-id",
                session_id,
                "- first line\nends with a semicolon;",
            ],
            "cwd": str(work),
            "token": None,
        }
        option = tmux("show-options", "-t", "=test-survive:", "remain-on-exit")
        assert option.stdout.strip() == "remain-on-exit on"

        assert cc.main(["list"]) == 0
        assert capsys.readouterr().out.startswith("test-survive running since ")

        # A running job isn't restored twice.
        assert cc.main(["restore"]) == 0
        assert capsys.readouterr().out == ""

        tmux("kill-server").check_returncode()
        start_server()
        assert cc.main(["restore"]) == 0
        assert capsys.readouterr().out == "restored: test-survive\n"
        [_, second] = wait_for_calls(calls, 2)
        assert second == {
            "argv": ["--remote-control", "Test: survive", "--resume", session_id],
            "cwd": str(work),
            "token": None,
        }

        # Typed text is echoed on the job's screen.
        assert cc.main(["send", "test-survive", "-v", "hi;"]) == 0
        deadline = time.monotonic() + 10
        while "-v hi;" not in tmux("capture-pane", "-p", "-t", "=test-survive:").stdout:
            assert time.monotonic() < deadline, "the message never reached the job"
            time.sleep(0.1)
        assert cc.main(["stop", "test-survive"]) == 0
        assert not (tmp_path / "jobs" / "test-survive.json").exists()
        assert cc.main(["stop", "test-survive"]) == 1
        assert capsys.readouterr().err == "can't find session: test-survive\n"
    finally:
        tmux("kill-server")
