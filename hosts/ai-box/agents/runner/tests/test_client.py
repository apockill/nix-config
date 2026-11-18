"""client.py: typed calls on the runner's socket, and its errors."""

from __future__ import annotations

import socket
import threading
from pathlib import Path

import httpx
import pytest
from agent_runner.api_types import StartRequest
from agent_runner.client import Client, ClientError, error_of, quote
from agent_runner.events import Event, Heartbeat, Prompted
from conftest import Service


def test_typed_calls(service: Service) -> None:
    c = service.client
    assert c.agents().default == "fake"
    s = c.start(StartRequest(name="job", dir=str(service.tmp), task="hello"))
    assert s.name == "job" and s.agent == "fake"
    service.wait_state("job", "idle")
    assert c.status("job").last_message == "echo: hello"
    assert [x.name for x in c.sessions().sessions] == ["job"]
    assert c.output("job", 1).lines == ["[turn ended: end_turn]"]
    assert c.send("job", "again").delivery == "sent"
    service.wait_state("job", "idle")
    assert c.cancel("job").state == "idle"
    stopped = c.stop("job", "done here")
    assert (stopped.state, stopped.reason) == ("stopped", "done here")
    events = list(c.events("/v1/sessions/job/events?since=0"))
    assert all(isinstance(e, Event) for e in events)
    prompts = [
        e.body for e in events if isinstance(e, Event) and isinstance(e.body, Prompted)
    ]
    assert [p.text for p in prompts] == ["hello", "again"]


def test_answer_and_stop_without_a_reason(service: Service) -> None:
    c = service.client
    c.start(StartRequest(name="p", dir=str(service.tmp), task="permission"))
    service.wait_state("p", "waiting")
    assert c.answer("p", "p1", {"option_id": "allow"}).pending == []
    service.wait_state("p", "idle")
    assert c.stop("p").reason == "stopped"


def test_refusals_carry_the_status(service: Service) -> None:
    with pytest.raises(ClientError, match="no session named ghost") as e:
        service.client.status("ghost")
    assert e.value.status == 404
    with pytest.raises(ClientError, match="no session named ghost") as e:
        list(service.client.events("/v1/sessions/ghost/events"))
    assert e.value.status == 404


def test_the_runner_isnt_running(tmp_path: Path) -> None:
    with pytest.raises(ClientError, match="the runner isn't running") as e:
        Client(str(tmp_path / "sock")).agents()
    assert "systemctl --user status agent-runner" in str(e.value)
    assert e.value.status == 0


class Stub:
    """A unix socket that answers every connection with the same bytes."""

    def __init__(self, path: Path, answer: bytes) -> None:
        self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.sock.bind(str(path))
        self.sock.listen()
        self.answer = answer
        threading.Thread(target=self.serve, daemon=True).start()

    def serve(self) -> None:
        while True:
            try:
                conn, _ = self.sock.accept()
            except OSError:
                return
            with conn:
                conn.recv(65536)
                conn.sendall(self.answer)


def http(body: bytes, status: str = "200 OK", kind: str = "application/json") -> bytes:
    return (
        f"HTTP/1.1 {status}\r\nContent-Type: {kind}\r\n"
        f"Content-Length: {len(body)}\r\nConnection: close\r\n\r\n".encode() + body
    )


def test_an_answer_that_isnt_json(tmp_path: Path) -> None:
    stub = tmp_path / "stub.sock"
    Stub(stub, http(b"<html>"))
    with pytest.raises(ClientError, match="the runner's answer isn't JSON"):
        Client(str(stub)).agents()


def test_an_answer_that_doesnt_fit(tmp_path: Path) -> None:
    stub = tmp_path / "stub.sock"
    Stub(stub, http(b'{"default": "claude"}'))
    with pytest.raises(ClientError, match="answer to /v1/agents doesn't fit") as e:
        Client(str(stub)).agents()
    assert "agents\n  Field required" in str(e.value)


def test_an_error_without_a_message(tmp_path: Path) -> None:
    stub = tmp_path / "stub.sock"
    Stub(stub, http(b"[]", "502 Bad Gateway"))
    with pytest.raises(ClientError, match="HTTP 502") as e:
        Client(str(stub)).sessions()
    assert e.value.status == 502


def test_an_odd_event(tmp_path: Path) -> None:
    stub = tmp_path / "stub.sock"
    Stub(stub, http(b'{"kind": "heartbeat", "ts": 1.0, "seq": 3}\n{"kind": "x"}\n'))
    stream = Client(str(stub)).events("/v1/events")
    assert next(stream) == Heartbeat(ts=1.0, seq=3)
    with pytest.raises(ClientError, match="the runner sent an odd event"):
        next(stream)


def test_helpers() -> None:
    assert quote("a b/c") == "a%20b%2Fc"
    assert error_of(httpx.Response(400, json={"error": "nope"})) == "nope"
    assert error_of(httpx.Response(400, json={"error": 3})) == "HTTP 400"
    assert error_of(httpx.Response(500, json="x")) == "HTTP 500"
    assert error_of(httpx.Response(502, content=b"<html>")) == "HTTP 502"


def test_a_socket_it_cant_reach_is_a_client_error(tmp_path: Path) -> None:
    # Longer than a unix socket's path may be (108 bytes).
    client = Client(str(tmp_path / ("x" * 120) / "sock"))
    with pytest.raises(ClientError, match="AF_UNIX path too long") as e:
        client.agents()
    assert e.value.status == 0
