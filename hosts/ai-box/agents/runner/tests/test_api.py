"""api.py: the routes, strict bodies and parameters, and the event streams."""

from __future__ import annotations

import json
import socket
from typing import Any

import pytest
from agent_runner.client import ClientError, UnixHTTPConnection
from conftest import Service


def raw(service: Service, request: bytes) -> bytes:
    """Send bytes as they are; everything the runner answers."""
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as sock:
        sock.settimeout(10)
        sock.connect(str(service.socket))
        sock.sendall(request)
        sock.shutdown(socket.SHUT_WR)
        out = b""
        while chunk := sock.recv(65536):
            out += chunk
        return out


def refused(service: Service, method: str, path: str, body: Any = None) -> ClientError:
    with pytest.raises(ClientError) as e:
        service.call(method, path, body)
    return e.value


def test_agents(service: Service) -> None:
    assert service.call("GET", "/v1/agents") == {
        "default": "fake",
        "agents": [
            "auto",
            "configmodel",
            "fake",
            "loadonly",
            "nosignin",
            "steering",
            "token",
        ],
    }


def test_unknown_fields_are_refused_by_name(service: Service) -> None:
    e = refused(
        service, "POST", "/v1/sessions", {"name": "x", "dir": "/", "tsak": "hi"}
    )
    assert (e.status, str(e)) == (400, "tsak: unknown field")
    e = refused(service, "POST", "/v1/sessions", {"name": "x", "dir": "/", "env": []})
    assert (e.status, str(e)) == (400, "env: must be an object")
    service.start_session("s")
    e = refused(service, "POST", "/v1/sessions/s/send", {"text": "hi", "x": 1})
    assert (e.status, str(e)) == (400, "x: unknown field")
    e = refused(service, "POST", "/v1/sessions/s/send", {"text": "  "})
    assert (e.status, str(e)) == (400, "text: the message")
    e = refused(service, "POST", "/v1/sessions/s/stop", {"why": "x"})
    assert (e.status, str(e)) == (400, "why: unknown field")
    e = refused(service, "POST", "/v1/sessions/s/cancel", {"now": True})
    assert (e.status, str(e)) == (400, "now: unknown field")
    e = refused(service, "POST", "/v1/sessions/s/requests/p1", ["allow"])
    assert (e.status, str(e)) == (400, "the body must be a JSON object")
    assert service.status("s")["state"] == "idle"


def test_restart_takes_no_fields(service: Service) -> None:
    e = refused(service, "POST", "/v1/restart", {"soon": True})
    assert e.status == 400
    # Not restarting: the service still answers.
    assert service.call("GET", "/v1/sessions") == {"sessions": []}


def test_a_body_that_isnt_json(service: Service) -> None:
    answer = raw(
        service,
        b"POST /v1/sessions HTTP/1.1\r\nContent-Length: 5\r\n\r\n{name",
    )
    head, body = answer.split(b"\r\n\r\n", 1)
    assert head.startswith(b"HTTP/1.1 400 Bad Request")
    assert json.loads(body)["error"].startswith("the body isn't JSON")


def test_not_http_gets_no_answer(service: Service) -> None:
    assert raw(service, b"hello\r\n\r\n") == b""
    assert raw(service, b"GET /v1/sessions HTTP/1.1\r\n") == b""


def test_parameters_must_be_numbers(service: Service) -> None:
    service.start_session("s")
    e = refused(service, "GET", "/v1/sessions/s/output?lines=all")
    assert (e.status, str(e)) == (400, "lines: a whole number, not 'all'")
    conn = UnixHTTPConnection(str(service.socket), timeout=10)
    conn.request("GET", "/v1/events?since=x")
    resp = conn.getresponse()
    assert resp.status == 400
    assert json.loads(resp.read())["error"] == "since: a whole number, not 'x'"


@pytest.mark.parametrize(
    "method, path, error",
    [
        ("GET", "/v2/sessions", "unknown path"),
        ("GET", "/", "unknown path"),
        ("GET", "/v1/nothing", "no GET /v1/nothing"),
        ("DELETE", "/v1/sessions/s", "no DELETE /v1/sessions/s"),
        ("GET", "/v1/sessions/ghost", "no session named ghost"),
        ("POST", "/v1/sessions/ghost/send", "no session named ghost"),
        ("GET", "/v1/sessions/ghost/events", "no session named ghost"),
    ],
)
def test_not_found(service: Service, method: str, path: str, error: str) -> None:
    e = refused(service, method, path, {"text": "x"} if method == "POST" else None)
    assert e.status == 404 and error in str(e)


def test_output_lines(service: Service) -> None:
    service.start_session("s", "hello")
    service.wait_state("s", "idle")
    out = service.call("GET", "/v1/sessions/s/output")["lines"]
    assert out == ["> hello", "echo: hello", "[turn ended: end_turn]"]
    assert service.call("GET", "/v1/sessions/s/output?lines=1")["lines"] == out[-1:]
    assert service.call("GET", "/v1/sessions/s/output?lines=0")["lines"] == []


def test_a_sessions_stream_has_only_its_events(service: Service) -> None:
    service.start_session("a", "hello")
    service.start_session("b", "hello")
    service.wait_state("a", "idle")
    service.wait_state("b", "idle")
    mine = service.events("a")
    assert mine and {e["session"] for e in mine} == {"a"}
    every = [
        json.loads(line)
        for line in raw(service, b"GET /v1/events?since=0 HTTP/1.1\r\n\r\n")
        .split(b"\r\n\r\n", 1)[1]
        .splitlines()
    ]
    assert {e["session"] for e in every} == {"a", "b"}
    seqs = [e["seq"] for e in every]
    assert seqs == sorted(seqs)
    # since= skips what the client has seen.
    later = list(service.client.events(f"/v1/sessions/a/events?since={mine[1]['seq']}"))
    assert [e.seq for e in later] == [e["seq"] for e in mine[2:]]


def test_start_answers_201_with_the_session(service: Service) -> None:
    conn = UnixHTTPConnection(str(service.socket), timeout=30)
    body = json.dumps({"name": "n", "dir": str(service.tmp), "task": "hello"})
    conn.request("POST", "/v1/sessions", body=body)
    resp = conn.getresponse()
    assert resp.status == 201
    s = json.loads(resp.read())
    assert s["name"] == "n" and s["state"] in ("running", "idle")
    assert resp.getheader("Content-Type") == "application/json"
