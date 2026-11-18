"""cli.py: every verb of `agent` against the service, and the tmux jobs from before it."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from agent_runner import cli
from conftest import Service
from test_jobs import fake_tmux, tmux_calls


class Agent:
    """`agent` with the service's socket, and a stand-in cc-tmux if given its jobs."""

    def __init__(self, service: Service, tmux_jobs: list[str] | None = None) -> None:
        self.service = service
        self.env = {
            "AGENT_RUNNER_SOCKET": str(service.socket),
            "PATH": "/the/callers/path",
            "TMPDIR": "/tmp/x",
        }
        if tmux_jobs is not None:
            self.env["AGENT_RUNNER_CC_TMUX"] = str(fake_tmux(service.tmp, tmux_jobs))

    def __call__(self, *argv: str) -> int:
        return cli.main(list(argv), self.env, "agent")


def task(service: Service, text: str) -> str:
    path = service.tmp / "task.md"
    path.write_text(text + "\n")
    return str(path)


def test_start_from_a_title_and_a_task_file(
    service: Service, capsys: pytest.CaptureFixture[str]
) -> None:
    agent = Agent(service)
    assert (
        agent("start", "Sites: the thing", str(service.tmp), task(service, "hello"))
        == 0
    )
    out = capsys.readouterr().out.splitlines()
    assert out[0] == "session: sites-the-thing"
    assert "name: sites-the-thing" in out and "origin: job: Sites: the thing" in out
    s = service.wait_state("sites-the-thing", "idle")
    assert s["last_message"] == "echo: hello"
    assert s["env"] == ["PATH", "TMPDIR"]


def test_start_options(service: Service, capsys: pytest.CaptureFixture[str]) -> None:
    agent = Agent(service)
    argv = ["start", "opts", str(service.tmp), "--task", "env", "--model", "small"]
    argv += ["--env", "RUNNER_TEST_VAR=yes", "--origin", "test", "--mode", "plan"]
    argv += ["--session-meta", '{"k": 1}']
    assert agent(*argv) == 0
    s = service.wait_state("opts", "idle")
    assert s["last_message"].startswith("RUNNER_TEST_VAR=yes")
    assert (s["model"], s["mode"], s["origin"], s["session_meta"]) == (
        "small",
        "plan",
        "test",
        {"k": 1},
    )
    assert agent("start", "idle-one", str(service.tmp)) == 0
    assert service.status("idle-one")["turns"] == 0


@pytest.mark.parametrize(
    "argv, error",
    [
        (["start", "!!", "."], "needs a letter or digit"),
        (["start", "job", "/nonexistent"], "isn't a directory"),
        (["start", "job", ".", "/nonexistent"], "can't read the task file"),
        (["start", "job", ".", "conftest.py", "--task", "x"], "not both"),
        (["start", "job", ".", "--agent", "nobody"], "agent must be one of"),
    ],
)
def test_start_refuses(
    service: Service,
    capsys: pytest.CaptureFixture[str],
    argv: list[str],
    error: str,
) -> None:
    assert Agent(service)(*argv) == 1
    assert error in capsys.readouterr().err
    assert service.call("GET", "/v1/sessions") == {"sessions": []}


@pytest.mark.parametrize(
    "argv, error",
    [
        (["start", "job", ".", "--env", "NOEQUALS"], "--env takes NAME=value"),
        (["start", "job", ".", "--session-meta", "[1]"], "takes a JSON object"),
        (["start", "job", ".", "--session-meta", "{"], "isn't JSON"),
        (["answer", "j", "q1", "--decline", "--cancel"], "not allowed with"),
        (["peek", "j", "many"], "invalid int value"),
        (["nope"], "invalid choice"),
        ([], "required"),
    ],
)
def test_usage(
    service: Service, capsys: pytest.CaptureFixture[str], argv: list[str], error: str
) -> None:
    with pytest.raises(SystemExit) as e:
        Agent(service)(*argv)
    assert e.value.code == 2
    err = capsys.readouterr().err
    assert error in err and "agent: " in err


def test_the_session_verbs(
    service: Service, capsys: pytest.CaptureFixture[str]
) -> None:
    agent = Agent(service)
    service.start_session("job", "hello")
    service.wait_state("job", "idle")
    capsys.readouterr()
    assert agent("send", "job", "hello", "--there") == 0
    assert capsys.readouterr().out == "sent\n"
    service.wait_state("job", "idle")
    assert agent("peek", "job", "2") == 0
    assert capsys.readouterr().out == "echo: hello --there\n[turn ended: end_turn]\n"
    (service.tmp / "msg").write_text("from a file\n")
    assert agent("send", "--file", str(service.tmp / "msg"), "job") == 0
    service.wait_state("job", "idle")
    assert service.status("job")["last_message"] == "echo: from a file"
    capsys.readouterr()
    assert agent("status", "job", "--json") == 0
    status = json.loads(capsys.readouterr().out)
    assert status["name"] == "job" and status["turns"] == 3
    assert agent("status", "job") == 0
    assert "state: idle" in capsys.readouterr().out.splitlines()
    assert agent("transcript", "job") == 0
    assert capsys.readouterr().out == status["transcript"] + "\n"
    assert agent("events", "job") == 0
    events = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
    assert {e["session"] for e in events} == {"job"}
    assert agent("events", "--since", str(events[-2]["seq"])) == 0
    assert [json.loads(x)["seq"] for x in capsys.readouterr().out.splitlines()] == [
        events[-1]["seq"]
    ]
    assert agent("cancel", "job") == 0
    assert "state: idle" in capsys.readouterr().out
    assert agent("wait", "job", "--idle", "0", "--every", "0.05") == 0
    assert capsys.readouterr().out.startswith("IDLE (idle, quiet ")
    assert agent("stop", "job", "--reason", "all done") == 0
    out = capsys.readouterr().out.splitlines()
    assert "state: stopped" in out and "reason: all done" in out
    assert agent("send", "job") == 1
    assert "send needs a message" in capsys.readouterr().err
    assert agent("send", "job", "more") == 1
    assert "job is stopped" in capsys.readouterr().err


def test_answers(service: Service, capsys: pytest.CaptureFixture[str]) -> None:
    agent = Agent(service)
    service.start_session("p", "permission")
    service.wait_state("p", "waiting")
    assert agent("status", "p") == 0
    assert "pending permission p1: touch x" in capsys.readouterr().out
    assert agent("answer", "p", "p1", "allow") == 0
    assert service.wait_state("p", "idle")["last_message"].endswith('"allow"}')
    service.start_session("q", "question")
    service.wait_state("q", "waiting")
    assert agent("answer", "q", "q1", '{"colour": "blue"}') == 0
    assert service.wait_state("q", "idle")["last_message"] == (
        'question: {"action": "accept", "content": {"colour": "blue"}}'
    )
    capsys.readouterr()
    assert agent("answer", "q", "x1", "y") == 1
    assert "isn't a request id" in capsys.readouterr().err
    assert agent("answer", "q", "q1", "{}") == 1
    assert "q has no open request q1" in capsys.readouterr().err


def test_list(service: Service, capsys: pytest.CaptureFixture[str]) -> None:
    agent = Agent(service)
    assert agent("list") == 0
    assert capsys.readouterr().out == "no sessions\n"
    service.start_session("a", "permission", model="small")
    service.wait_state("a", "waiting")
    assert agent("list") == 0
    [line] = capsys.readouterr().out.splitlines()
    assert line.startswith("a waiting fake/small since ")
    assert line.endswith(" (1 waiting for an answer)")
    assert agent("list", "--json") == 0
    [listed] = json.loads(capsys.readouterr().out)
    assert listed["name"] == "a" and listed["pending"] == 1


def test_tmux_jobs_go_to_cc_tmux(
    service: Service, capfd: pytest.CaptureFixture[str]
) -> None:
    agent = Agent(service, ["old-job"])
    service.start_session("new-job")
    assert agent("send", "new-job", "hello") == 0
    assert agent("send", "old-job", "hello", "--there") == 0
    assert agent("peek", "old-job", "5") == 0
    assert agent("stop", "old-job") == 3  # cc-tmux's own exit code
    assert agent("stop", "new-job") == 0
    calls = [c for c in tmux_calls(service.tmp) if c[0] != "list"]
    assert calls == [
        ["send", "old-job", "hello --there"],
        ["peek", "old-job", "5"],
        ["stop", "old-job"],
    ]
    assert service.status("new-job")["state"] == "stopped"
    capfd.readouterr()
    assert agent("peek", "ghost") == 1
    assert "no session named ghost" in capfd.readouterr().err
    assert agent("wait", "old-job") == 1
    assert "tmux-legacy/cc-wait.sh" in capfd.readouterr().err


def test_list_shows_both(service: Service, capfd: pytest.CaptureFixture[str]) -> None:
    agent = Agent(service, ["old-job"])
    service.start_session("new-job")
    capfd.readouterr()
    assert agent("list") == 0
    out = capfd.readouterr().out.splitlines()
    assert out[0].startswith("new-job idle fake since ")
    assert out[1:] == [
        "in tmux, from before the runner (Remote Control):",
        "  old-job running since today",
    ]
    service.call("POST", "/v1/sessions/new-job/stop", {})


def test_a_title_still_running_in_tmux_isnt_started_again(
    service: Service, capsys: pytest.CaptureFixture[str]
) -> None:
    agent = Agent(service, ["old-job"])
    assert agent("start", "Old job", str(service.tmp), task(service, "x")) == 1
    assert "still running in tmux" in capsys.readouterr().err
    assert service.call("GET", "/v1/sessions") == {"sessions": []}


def test_without_the_runner(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert cli.main(["list"], {}, "agent") == 1
    assert "agent: AGENT_RUNNER_SOCKET isn't set" in capsys.readouterr().err
    env = {"AGENT_RUNNER_SOCKET": str(tmp_path / "sock")}
    assert cli.main(["list"], env, "cc") == 1
    assert capsys.readouterr().err.startswith("cc: the runner isn't running")


def test_restart(service: Service, capsys: pytest.CaptureFixture[str]) -> None:
    assert Agent(service)("restart") == 0
    assert "restarting" in capsys.readouterr().out
    assert service.thread
    service.thread.join(20)
    assert service.exit_code == 75
    service.thread = None
