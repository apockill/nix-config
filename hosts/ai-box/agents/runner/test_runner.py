"""Tests for runner.py, against fake_acp_agent.py. Run with `just test`."""

from __future__ import annotations

import asyncio
import json
import os
import re
import sys
import threading
import time
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

import pytest
import runner
from runner import Client, CliError

FAKE = str(Path(__file__).with_name("fake_acp_agent.py"))


class Service:
    """The runner's service in a thread of its own, on a scratch socket and state folder."""

    def __init__(self, tmp: Path, agents: dict[str, Any]) -> None:
        self.tmp = tmp
        self.socket = tmp / "run" / "sock"
        self.state = tmp / "state"
        self.notified = tmp / "notified.txt"
        self.agents_file = tmp / "agents.json"
        self.agents_file.write_text(json.dumps(agents))
        self.client = Client(str(self.socket))
        self.thread: threading.Thread | None = None
        self.exit_code: int | None = None

    def start(self) -> None:
        loop = asyncio.new_event_loop()
        stop = asyncio.Event()
        self.loop, self.stop_event = loop, stop
        notify = ["sh", "-c", f'printf "%s\\n" "$1" >> {self.notified}', "notify"]

        def run() -> None:
            self.exit_code = loop.run_until_complete(
                runner.serve(self.socket, self.state, self.agents_file, notify, stop)
            )

        self.thread = threading.Thread(target=run, daemon=True)
        self.thread.start()
        wait_for(self.socket.exists)

    def stop(self) -> None:
        if self.thread:
            self.loop.call_soon_threadsafe(self.stop_event.set)
            self.thread.join(20)
            self.thread = None

    def call(self, method: str, path: str, body: Any = None) -> Any:
        return self.client.call(method, path, body)

    def start_session(
        self, name: str, task: str | None = None, **extra: Any
    ) -> dict[str, Any]:
        body = {"name": name, "dir": str(self.tmp), **extra}
        if task is not None:
            body["task"] = task
        result: dict[str, Any] = self.call("POST", "/v1/sessions", body)
        return result

    def status(self, name: str) -> dict[str, Any]:
        result: dict[str, Any] = self.call("GET", f"/v1/sessions/{name}")
        return result

    def wait_state(self, name: str, *states: str) -> dict[str, Any]:
        return wait_for(lambda: (s := self.status(name))["state"] in states and s)

    def events(self, name: str) -> list[dict[str, Any]]:
        return list(self.client.events(f"/v1/sessions/{name}/events?since=0"))


def wait_for(check: Callable[[], Any], timeout: float = 15) -> Any:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if value := check():
            return value
        time.sleep(0.05)
    raise AssertionError(f"timed out waiting for {check}")


def fake_agent(**env: str) -> dict[str, Any]:
    return {
        "command": [sys.executable, FAKE],
        "env": env,
        "transcript": "/t/{cwd_slug}/{session_id}.jsonl",
    }


@pytest.fixture
def service(tmp_path: Path) -> Iterator[Service]:
    s = Service(
        tmp_path,
        {
            "default": "fake",
            "agents": {
                "fake": fake_agent(FAKE_LOG=str(tmp_path / "fake.log")),
                "steering": fake_agent(FAKE_STEERING="1"),
                "nosignin": fake_agent(FAKE_AUTH="fail-new"),
                "auto": {
                    **fake_agent(),
                    "mode": "auto",
                    "claude_trust_file": str(tmp_path / "claude.json"),
                },
                "token": {**fake_agent(), "pass_env": ["PASSED_TOKEN"]},
            },
            "refused_env": ["ANTHROPIC_API_KEY"],
        },
    )
    s.start()
    yield s
    s.stop()


def agent_log(service: Service) -> list[dict[str, Any]]:
    return [
        json.loads(line) for line in (service.tmp / "fake.log").read_text().splitlines()
    ]


def test_start_runs_the_task_and_records_the_session(service: Service) -> None:
    s = service.start_session("job-1", "hello")
    assert s["agent"] == "fake"
    sid = s["agent_session_id"]
    assert (
        s["transcript"]
        == f"/t/{re.sub('[^A-Za-z0-9]', '-', str(service.tmp))}/{sid}.jsonl"
    )
    done = service.wait_state("job-1", "idle")
    assert done["last_message"] == "echo: hello"
    assert done["turns"] == 1
    assert done["last_event_at"] >= done["created_at"]
    kinds = [e["kind"] for e in service.events("job-1")]
    assert kinds.index("prompt") < kinds.index("turn_end")
    out = service.call("GET", "/v1/sessions/job-1/output?lines=10")["lines"]
    assert out == ["> hello", "echo: hello", "[turn ended: end_turn]"]
    # The client offers form elicitation, so Claude keeps AskUserQuestion.
    init = next(m for m in agent_log(service) if m.get("method") == "initialize")
    assert init["params"]["clientCapabilities"]["elicitation"] == {"form": {}}
    record = json.loads(
        (service.state / "sessions" / "job-1" / "session.json").read_text()
    )
    assert record["agent_session_id"] == sid


def test_mode_model_and_trust(service: Service) -> None:
    service.start_session("job", "hello", agent="auto", model="small")
    trust = json.loads((service.tmp / "claude.json").read_text())
    assert trust["projects"][str(service.tmp)]["hasTrustDialogAccepted"] is True
    with pytest.raises(CliError, match="no model 'huge'"):
        service.start_session("job2", "hello", agent="auto", model="huge")
    assert service.status("job2")["state"] == "failed"


def test_a_missing_sign_in_fails_loudly(service: Service) -> None:
    with pytest.raises(CliError, match="sign-in is missing or expired"):
        service.start_session("nope", "hello", agent="nosignin")
    assert service.status("nope")["state"] == "failed"
    assert "nope (nosignin) failed" in wait_for(
        lambda: service.notified.exists() and service.notified.read_text()
    )
    notified = wait_for(
        lambda: [e for e in service.events("nope") if e["kind"] == "notified"]
    )
    assert notified[0]["ok"] is True


def test_a_sign_in_rejected_on_the_first_prompt_fails_the_start(
    service: Service,
) -> None:
    with pytest.raises(CliError, match="sign-in is missing or expired.*401"):
        service.start_session("bad", "auth")
    assert service.status("bad")["state"] == "failed"
    assert wait_for(
        lambda: service.notified.exists()
        and "bad (fake) failed" in service.notified.read_text()
    )


def test_permission_requests_wait_for_an_answer(service: Service) -> None:
    service.start_session("perm", "permission")
    s = service.wait_state("perm", "waiting")
    [pending] = s["pending"]
    assert pending["kind"] == "permission" and pending["title"] == "touch x"
    with pytest.raises(CliError, match="option_id must be one of allow, reject"):
        service.call(
            "POST",
            f"/v1/sessions/perm/requests/{pending['request_id']}",
            {"option_id": "maybe"},
        )
    service.call(
        "POST",
        f"/v1/sessions/perm/requests/{pending['request_id']}",
        {"option_id": "allow"},
    )
    done = service.wait_state("perm", "idle")
    assert (
        done["last_message"]
        == 'permission: {"outcome": "selected", "optionId": "allow"}'
    )
    assert (
        "[permission p1] touch x (allow, reject)"
        in service.call("GET", "/v1/sessions/perm/output")["lines"]
    )


def test_questions_are_answered_as_forms(service: Service) -> None:
    service.start_session("q", "question")
    [pending] = service.wait_state("q", "waiting")["pending"]
    assert pending["kind"] == "question" and pending["schema"]["properties"]["colour"][
        "enum"
    ] == ["red", "blue"]
    service.call(
        "POST",
        f"/v1/sessions/q/requests/{pending['request_id']}",
        {"action": "accept", "content": {"colour": "blue"}},
    )
    assert (
        service.wait_state("q", "idle")["last_message"]
        == 'question: {"action": "accept", "content": {"colour": "blue"}}'
    )


def test_a_message_during_a_turn_is_queued_then_sent(service: Service) -> None:
    service.start_session("busy", "slow")
    service.wait_state("busy", "running")
    assert (
        service.call("POST", "/v1/sessions/busy/send", {"text": "next"})["delivery"]
        == "queued"
    )
    assert service.status("busy")["queued"] == ["next"]
    service.call("POST", "/v1/sessions/busy/cancel", {})
    # Cancel drops the queue too.
    wait_for(lambda: service.status("busy")["state"] == "idle")
    assert service.status("busy")["queued"] == []
    assert (
        service.call("POST", "/v1/sessions/busy/send", {"text": "slow"})["delivery"]
        == "sent"
    )
    service.wait_state("busy", "running")
    service.call("POST", "/v1/sessions/busy/cancel", {})
    assert service.wait_state("busy", "idle")["turns"] == 2


def test_steering_goes_into_the_running_turn(service: Service) -> None:
    service.start_session("steer", "slow", agent="steering")
    service.wait_state("steer", "running")
    assert (
        service.call("POST", "/v1/sessions/steer/send", {"text": "also this"})[
            "delivery"
        ]
        == "steered"
    )
    service.call("POST", "/v1/sessions/steer/cancel", {})
    service.wait_state("steer", "idle")


def test_the_runner_keeps_listening_after_the_turn(service: Service) -> None:
    service.start_session("late", "later")
    wait_for(lambda: service.status("late")["last_message"] == "now and later")
    kinds = [e["kind"] for e in service.events("late")]
    assert kinds.index("turn_end") < len(kinds) - 1


def test_live_event_stream(service: Service) -> None:
    service.start_session("live")
    got: list[dict[str, Any]] = []

    def follow() -> None:
        for event in service.client.events("/v1/events?follow=1"):
            got.append(event)
            if event["kind"] == "turn_end":
                return

    reader = threading.Thread(target=follow, daemon=True)
    reader.start()
    time.sleep(0.3)
    service.call("POST", "/v1/sessions/live/send", {"text": "hi"})
    reader.join(10)
    assert [e["kind"] for e in got if e["kind"] in ("prompt", "turn_end")] == [
        "prompt",
        "turn_end",
    ]
    seqs = [e["seq"] for e in got if e["kind"] != "heartbeat"]
    assert seqs == sorted(seqs)


def test_environment_refusals_and_pass_through(
    service: Service, monkeypatch: pytest.MonkeyPatch
) -> None:
    with pytest.raises(CliError, match="ANTHROPIC_API_KEY would switch"):
        service.start_session("e", "env", env={"ANTHROPIC_API_KEY": "x"})
    os.environ["ANTHROPIC_API_KEY"] = "leaked"
    try:
        service.start_session("e2", "env", env={"RUNNER_TEST_VAR": "yes"})
        assert (
            service.wait_state("e2", "idle")["last_message"]
            == "RUNNER_TEST_VAR=yes ANTHROPIC_API_KEY=- PASSED_TOKEN=-"
        )
        # pass_env is required: no token, no session.
        with pytest.raises(CliError, match="no PASSED_TOKEN"):
            service.start_session("t", "env", agent="token")
        os.environ["PASSED_TOKEN"] = "tok"
        service.start_session("t2", "env", agent="token")
        assert service.wait_state("t2", "idle")["last_message"].endswith(
            "PASSED_TOKEN=tok"
        )
    finally:
        os.environ.pop("ANTHROPIC_API_KEY", None)
        os.environ.pop("PASSED_TOKEN", None)


def test_a_crashed_agent_fails_loudly(service: Service) -> None:
    # The agent dies on the task: the start fails, with the reason.
    with pytest.raises(CliError, match="exited"):
        service.start_session("crash", "exit")
    s = service.wait_state("crash", "failed")
    assert "exited (code 3)" in s["reason"]
    assert wait_for(
        lambda: service.notified.exists()
        and "crash (fake) failed" in service.notified.read_text()
    )
    # A failed session that had started can be resumed with a message.
    assert (
        service.call("POST", "/v1/sessions/crash/send", {"text": "hello"})["delivery"]
        == "sent"
    )
    assert service.wait_state("crash", "idle")["last_message"] == "echo: hello"


def test_stop_then_restart_with_the_same_name(service: Service) -> None:
    service.start_session("s", "hello")
    service.wait_state("s", "idle")
    service.call("POST", "/v1/sessions/s/stop", {})
    assert service.status("s")["state"] == "stopped"
    with pytest.raises(CliError, match="stopped"):
        service.call("POST", "/v1/sessions/s/send", {"text": "x"})
    with pytest.raises(CliError, match="is idle; stop it first"):
        service.start_session("t", "hello")
        service.wait_state("t", "idle")
        service.start_session("t", "hello")
    assert service.start_session("s", "hello")["state"] in ("running", "idle")


def test_sessions_outlive_a_runner_restart_and_resume(service: Service) -> None:
    sid = service.start_session("keep", "hello", model="big")["agent_session_id"]
    service.wait_state("keep", "idle")
    service.stop()
    service.start()
    s = service.status("keep")
    assert s["state"] == "offline" and "a message resumes it" in s["reason"]
    assert s["last_event_at"] > 0
    # The model must be set again on resume; the fake's resumed session only offers "small".
    service.call("POST", "/v1/sessions/keep/stop", {})
    service.start_session("keep2", "hello", model="small")
    service.wait_state("keep2", "idle")
    service.stop()
    service.start()
    assert (
        service.call("POST", "/v1/sessions/keep2/send", {"text": "again"})["delivery"]
        == "sent"
    )
    done = service.wait_state("keep2", "idle")
    assert done["last_message"] == "echo: again"
    resumes = [m for m in agent_log(service) if m.get("method") == "session/resume"]
    assert resumes and resumes[-1]["params"]["sessionId"] == done["agent_session_id"]
    assert sid != done["agent_session_id"]
    seqs = [e["seq"] for e in service.events("keep2")]
    assert seqs == sorted(set(seqs))


def test_bad_requests(service: Service) -> None:
    with pytest.raises(CliError, match="name: lowercase"):
        service.start_session("Bad Name")
    with pytest.raises(CliError, match="agent must be one of"):
        service.start_session("x", agent="nobody")
    with pytest.raises(CliError, match="no session named ghost"):
        service.status("ghost")
    with pytest.raises(CliError, match="has no open request"):
        service.start_session("y", "hello")
        service.call("POST", "/v1/sessions/y/requests/p9", {"option_id": "allow"})


def test_render() -> None:
    def chunk(text: str) -> dict[str, Any]:
        return {
            "kind": "update",
            "update": {
                "sessionUpdate": "agent_message_chunk",
                "content": {"type": "text", "text": text},
            },
        }

    events = [
        {"kind": "prompt", "text": "do it\nnow"},
        chunk("Sure, "),
        chunk("on it.\nSecond line"),
        {
            "kind": "update",
            "update": {"sessionUpdate": "tool_call", "title": "Bash ls"},
        },
        {
            "kind": "update",
            "update": {
                "sessionUpdate": "tool_call_update",
                "status": "failed",
                "toolCallId": "t1",
            },
        },
        {
            "kind": "question",
            "request_id": "q1",
            "message": "Pick",
            "schema": {
                "properties": {
                    "c": {
                        "title": "Colour",
                        "oneOf": [{"const": "red"}, {"const": "blue"}],
                    }
                }
            },
        },
        {"kind": "turn_end", "stop_reason": "end_turn"},
        {"kind": "state", "state": "failed", "reason": "boom"},
    ]
    assert runner.render(events) == [
        "> do it now",
        "Sure, on it.",
        "Second line",
        "[tool] Bash ls",
        "[tool failed] t1",
        "[question q1] Pick",
        "  c: Colour [red | blue]",
        "[turn ended: end_turn]",
        "[failed] boom",
    ]


def test_cli_against_the_service(
    service: Service,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("AGENT_RUNNER_SOCKET", str(service.socket))
    task = service.tmp / "task.txt"
    task.write_text("hello\n")
    assert (
        runner.main(
            [
                "start",
                "cli",
                "--dir",
                str(service.tmp),
                "--task-file",
                str(task),
                "--origin",
                "test",
            ]
        )
        == 0
    )
    assert "name: cli" in capsys.readouterr().out
    service.wait_state("cli", "idle")
    assert runner.main(["peek", "cli", "2"]) == 0
    assert capsys.readouterr().out == "echo: hello\n[turn ended: end_turn]\n"
    assert runner.main(["list"]) == 0
    assert capsys.readouterr().out.startswith("cli idle fake since ")
    with pytest.raises(SystemExit):
        runner.main(["status", "ghost"])
    assert "no session named ghost" in capsys.readouterr().err


def test_restart_exits_for_systemd_to_start_it_again(service: Service) -> None:
    service.start_session("r", "hello")
    service.wait_state("r", "idle")
    assert service.call("POST", "/v1/restart", {}) == {"restarting": True}
    assert service.thread
    service.thread.join(20)
    assert service.exit_code == runner.RESTART_EXIT
    service.thread = None
    service.start()
    assert service.status("r")["state"] == "offline"
