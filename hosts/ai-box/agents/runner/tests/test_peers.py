"""peers.py: telling a caller inside a session from one outside, and refusing the ones that may
not use the runner; against a /proc of its own, and end to end from a session's tool process.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from agent_runner.errors import RunnerError
from agent_runner.peers import Caller, Peers, admit, marker
from conftest import Service

RUNNER = "/run/runner/sock"


def process(
    proc: Path,
    pid: int,
    ppid: int,
    env: dict[str, str] | None = None,
    cgroup: str = "/user.slice",
    comm: str = "sh",
) -> None:
    folder = proc / str(pid)
    folder.mkdir(parents=True)
    (folder / "stat").write_text(f"{pid} ({comm}) S {ppid} {pid} {pid} 0 -1\n")
    environ = b"".join(f"{k}={v}".encode() + b"\0" for k, v in (env or {}).items())
    (folder / "environ").write_bytes(environ)
    (folder / "cgroup").write_text(f"0::{cgroup}\n")


@pytest.fixture
def proc(tmp_path: Path) -> Path:
    """The runner (100, in its service's cgroup) with one agent (200); a tool of the agent's
    (300 -> 301, its comm with a space and a parenthesis); Hermes (500) elsewhere."""
    proc = tmp_path / "proc"
    service = (
        "/user.slice/user-993.slice/user@993.service/app.slice/agent-runner.service"
    )
    process(proc, 100, 1, cgroup=service)
    process(proc, 200, 100, marker("job", RUNNER), service)
    process(proc, 300, 200, marker("job", RUNNER), service, comm="bash -c (x)")
    process(proc, 301, 300, marker("job", RUNNER), service)
    process(proc, 500, 1)
    return proc


def test_the_marker() -> None:
    assert marker("job", RUNNER) == {
        "AGENT_RUNNER_SESSION": "job",
        "AGENT_RUNNER_OF": RUNNER,
    }


def test_ancestry(proc: Path) -> None:
    peers = Peers(RUNNER, proc=proc)
    assert peers.ancestry(301) == [301, 300, 200, 100]
    assert peers.ancestry(500) == [500]
    assert peers.ancestry(999) == [999]


def test_a_descendant_of_an_agent_is_its_session(proc: Path) -> None:
    peers = Peers(RUNNER, own_cgroup=True, proc=proc)
    caller = peers.identify(301, {200: "job"}, 100)
    assert caller == Caller(301, True, "job", "its agent's process tree")
    assert peers.identify(500, {200: "job"}, 100) == Caller(500)


def test_a_process_that_left_the_tree_keeps_the_marker(proc: Path) -> None:
    process(proc, 400, 1, marker("job", RUNNER), "/elsewhere")
    caller = Peers(RUNNER, proc=proc).identify(400, {200: "job"}, 100)
    assert caller == Caller(400, True, None, "AGENT_RUNNER_SESSION=job")
    # Another runner's marker (a private runner's sessions) isn't this one's business.
    process(proc, 401, 1, marker("job", "/other/sock"), "/elsewhere")
    assert Peers(RUNNER, proc=proc).identify(401, {200: "job"}, 100) == Caller(401)


def test_one_without_the_marker_is_still_in_the_runners_cgroup(proc: Path) -> None:
    service = (proc / "100" / "cgroup").read_text()[3:].strip()
    process(proc, 402, 1, {}, service)
    assert Peers(RUNNER, proc=proc).identify(402, {}, 100) == Caller(402)
    caller = Peers(RUNNER, own_cgroup=True, proc=proc).identify(402, {}, 100)
    assert caller == Caller(402, True, None, f"the runner's cgroup {service}")


def test_the_runner_itself_and_a_process_gone_are_outside(proc: Path) -> None:
    peers = Peers(RUNNER, own_cgroup=True, proc=proc)
    assert peers.identify(100, {200: "job"}, 100) == Caller(100)
    assert peers.identify(999, {200: "job"}, 100) == Caller(999)


def test_admit() -> None:
    admit(Caller(5), {})
    admit(Caller(5, True, "hermes-job"), {"hermes-job": True})
    with pytest.raises(RunnerError, match="inside session builder, which may not") as e:
        admit(Caller(5, True, "builder"), {"builder": False})
    assert e.value.status == 403
    with pytest.raises(RunnerError, match="can't tell which"):
        admit(Caller(5, True, None, "AGENT_RUNNER_SESSION=x"), {"x": True})


def said(service: Service, name: str, text: str) -> str:
    service.call("POST", f"/v1/sessions/{name}/send", {"text": text})
    message: str = service.wait_state(name, "idle")["last_message"]
    return message


def test_a_session_may_not_use_the_runner_unless_allowed(service: Service) -> None:
    service.start_session("builder")
    service.wait_state("builder", "idle")
    out = said(service, "builder", f"call {service.socket} /v1/sessions")
    assert out.startswith("HTTP/1.1 403")
    assert "inside session builder, which may not use the runner" in out
    # Left its agent's tree, it still has the marker.
    out = said(service, "builder", f"call-escaped {service.socket} /v1/sessions")
    assert out.startswith("HTTP/1.1 403") and "can't tell which" in out
    service.start_session("hermes-job", allow_runner=True)
    service.wait_state("hermes-job", "idle")
    assert service.status("hermes-job")["allow_runner"] is True
    out = said(service, "hermes-job", f"call {service.socket} /v1/agents")
    assert out.startswith("HTTP/1.1 200") and '"default":"fake"' in out
    # From outside every session (the tests themselves): allowed.
    assert service.status("builder")["allow_runner"] is False
