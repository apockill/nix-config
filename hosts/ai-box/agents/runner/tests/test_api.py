"""api.py: the routes, strict bodies and parameters, the errors, and the event streams."""

from __future__ import annotations

import json
import socket
from typing import Any

import httpx
import pytest
from agent_runner import api
from agent_runner.client import ClientError
from agent_runner.errors import RunnerError
from agent_runner.runner import Runner
from conftest import Service


def http(service: Service) -> httpx.Client:
    return httpx.Client(
        transport=httpx.HTTPTransport(uds=str(service.socket)),
        base_url="http://runner",
        timeout=30,
    )


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
            "windowed",
        ],
    }


def test_unknown_fields_and_wrong_types_are_refused_by_name(service: Service) -> None:
    e = refused(
        service, "POST", "/v1/sessions", {"name": "x", "dir": "/", "tsak": "hi"}
    )
    assert (e.status, str(e)) == (400, "tsak: Extra inputs are not permitted")
    e = refused(service, "POST", "/v1/sessions", {"name": "x", "dir": "/", "env": []})
    assert (e.status, str(e)) == (400, "env: Input should be a valid dictionary")
    e = refused(service, "POST", "/v1/sessions", {"name": 7, "dir": "/"})
    assert (e.status, str(e)) == (400, "name: Input should be a valid string")
    service.start_session("s")
    e = refused(service, "POST", "/v1/sessions/s/send", {"text": "hi", "x": 1})
    assert (e.status, str(e)) == (400, "x: Extra inputs are not permitted")
    e = refused(service, "POST", "/v1/sessions/s/send", {"text": "  "})
    assert (e.status, str(e)) == (400, "text: the message")
    e = refused(service, "POST", "/v1/sessions/s/stop", {"why": "x"})
    assert (e.status, str(e)) == (400, "why: Extra inputs are not permitted")
    e = refused(service, "POST", "/v1/sessions/s/cancel", {"now": True})
    assert (e.status, str(e)) == (400, "now: Extra inputs are not permitted")
    e = refused(service, "POST", "/v1/sessions/s/requests/p1", ["allow"])
    assert (e.status, str(e)) == (400, "the body must be a JSON object")
    assert service.status("s")["state"] == "idle"


def test_restart_takes_no_fields(service: Service) -> None:
    e = refused(service, "POST", "/v1/restart", {"soon": True})
    assert (e.status, str(e)) == (400, "soon: Extra inputs are not permitted")
    # Not restarting: the service still answers.
    assert service.call("GET", "/v1/sessions") == {"sessions": []}


def test_a_body_that_isnt_json(service: Service) -> None:
    with http(service) as c:
        r = c.post(
            "/v1/sessions",
            content=b"{name",
            headers={"Content-Type": "application/json"},
        )
    assert r.status_code == 400
    assert r.json()["error"].startswith("the body isn't JSON")


def test_not_http_is_refused(service: Service) -> None:
    answer = raw(service, b"hello\r\n\r\n")
    assert answer == b"" or answer.startswith(b"HTTP/1.1 400")


def test_parameters_must_be_numbers(service: Service) -> None:
    service.start_session("s")
    e = refused(service, "GET", "/v1/sessions/s/output?lines=all")
    assert (e.status, str(e)) == (400, "lines: a whole number, not 'all'")
    with http(service) as c:
        r = c.get("/v1/events?since=x")
    assert r.status_code == 400
    assert r.json() == {"error": "since: a whole number, not 'x'"}


@pytest.mark.parametrize(
    "method, path, error",
    [
        ("GET", "/v2/sessions", "no GET /v2/sessions"),
        ("GET", "/", "no GET /"),
        ("GET", "/v1/nothing", "no GET /v1/nothing"),
        ("GET", "/v1/sessions/ghost", "no session named ghost"),
        ("POST", "/v1/sessions/ghost/send", "no session named ghost"),
        ("GET", "/v1/sessions/ghost/output", "no session named ghost"),
    ],
)
def test_not_found(service: Service, method: str, path: str, error: str) -> None:
    e = refused(service, method, path, {"text": "x"} if method == "POST" else None)
    assert e.status == 404 and error in str(e)


def test_the_events_of_an_unknown_session_are_a_404_not_a_stream(
    service: Service,
) -> None:
    with http(service) as c:
        r = c.get("/v1/sessions/ghost/events?follow=1")
    assert r.status_code == 404
    assert r.headers["content-type"] == "application/json"
    assert r.json() == {"error": "no session named ghost"}


def test_a_wrong_method(service: Service) -> None:
    for method, path in (("DELETE", "/v1/sessions/s"), ("GET", "/v1/restart")):
        e = refused(service, method, path)
        assert e.status == 405, (method, path)
        assert str(e).startswith(f"Method Not Allowed: {method} {path}")


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
    with http(service) as c:
        r = c.get("/v1/events?since=0")
    assert r.headers["content-type"].startswith("application/x-ndjson")
    every = [json.loads(line) for line in r.text.splitlines()]
    assert {e["session"] for e in every} == {"a", "b"}
    seqs = [e["seq"] for e in every]
    assert seqs == sorted(seqs)
    # since= skips what the client has seen.
    later = list(service.client.events(f"/v1/sessions/a/events?since={mine[1]['seq']}"))
    assert [e.seq for e in later if not e.kind == "heartbeat"] == [
        e["seq"] for e in mine[2:]
    ]


def test_following_one_session_gets_only_its_live_events_and_heartbeats(
    service: Service, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(api, "HEARTBEAT_SECONDS", 0.3)
    service.start_session("a")
    service.start_session("b")
    got: list[dict[str, Any]] = []
    with http(service) as c, c.stream("GET", "/v1/sessions/a/events?follow=1") as r:
        lines = r.iter_lines()
        service.call("POST", "/v1/sessions/b/send", {"text": "hi"})
        service.call("POST", "/v1/sessions/a/send", {"text": "hi"})
        for line in lines:
            got.append(json.loads(line))
            if got[-1]["kind"] == "turn_end":
                break
        while got[-1]["kind"] != "heartbeat":
            got.append(json.loads(next(lines)))
    events = [e for e in got if e["kind"] != "heartbeat"]
    assert {e["session"] for e in events} == {"a"}
    beat = got[-1]
    assert set(beat) == {"kind", "ts", "seq"} and beat["seq"] >= events[-1]["seq"]


def test_start_answers_201_with_the_session(service: Service) -> None:
    with http(service) as c:
        r = c.post(
            "/v1/sessions", json={"name": "n", "dir": str(service.tmp), "task": "hello"}
        )
    assert r.status_code == 201
    s = r.json()
    assert s["name"] == "n" and s["state"] in ("running", "idle")
    assert r.headers["content-type"] == "application/json"


def broken(*_: Any) -> Any:
    raise RuntimeError("boom")


def test_an_internal_error_is_a_500_and_the_service_goes_on(
    service: Service, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(api, "render", broken)
    service.start_session("s")
    answer = raw(service, b"GET /v1/sessions/s/output HTTP/1.1\r\nHost: x\r\n\r\n")
    head, body = answer.split(b"\r\n\r\n", 1)
    assert head.startswith(b"HTTP/1.1 500")
    assert json.loads(body) == {"error": "internal error: RuntimeError('boom')"}
    assert service.status("s")["name"] == "s"


def test_the_cli_gets_an_internal_errors_message(
    service: Service, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(api, "render", broken)
    service.start_session("s")
    e = refused(service, "GET", "/v1/sessions/s/output")
    assert e.status == 500 and "internal error: RuntimeError('boom')" in str(e)


def test_a_500_leaves_the_connection_usable(
    service: Service, monkeypatch: pytest.MonkeyPatch
) -> None:
    # agent wait polls on one client: a 500 must not reset its next call (an exception handler
    # that re-raises would close the keep-alive connection).
    monkeypatch.setattr(api, "render", broken)
    service.start_session("s")
    for _ in range(3):
        assert refused(service, "GET", "/v1/sessions/s/output").status == 500
        assert service.client.status("s").name == "s"


def test_the_schema_lists_every_route_with_its_models(service: Service) -> None:
    with http(service) as c:
        schema = c.get("/v1/openapi.json").json()
        assert c.get("/docs").status_code == 404
        assert c.get("/redoc").status_code == 404

    def model(content: dict[str, Any]) -> str:
        """The model a body or answer names, else its media type."""
        for media, of in content.items():
            ref: str = of.get("schema", {}).get("$ref", media)
            return ref.removeprefix("#/components/schemas/")
        return "-"

    routes = {}
    for path, operations in schema["paths"].items():
        for method, op in operations.items():
            sent = model(op.get("requestBody", {}).get("content", {}))
            ok = next(code for code in op["responses"] if code.startswith("2"))
            answer = model(op["responses"][ok].get("content", {}))
            routes[f"{method.upper()} {path}"] = (sent, f"{ok} {answer}")
            for code, response in op["responses"].items():
                if not code.startswith("2"):
                    assert model(response["content"]) == "ErrorBody", (path, code)
            assert "422" not in op["responses"], path
    assert routes == {
        "POST /v1/restart": ("RestartRequest", "200 Restarting"),
        "GET /v1/agents": ("-", "200 AgentList"),
        "GET /v1/sessions": ("-", "200 SessionList"),
        "POST /v1/sessions": ("StartRequest", "201 SessionStatus"),
        "GET /v1/events": ("-", "200 application/x-ndjson"),
        "GET /v1/sessions/{name}": ("-", "200 SessionStatus"),
        "GET /v1/sessions/{name}/output": ("-", "200 Output"),
        "GET /v1/sessions/{name}/events": ("-", "200 application/x-ndjson"),
        "POST /v1/sessions/{name}/send": ("SendRequest", "200 Sent"),
        "POST /v1/sessions/{name}/cancel": ("EmptyRequest", "200 SessionStatus"),
        "POST /v1/sessions/{name}/stop": ("StopRequest", "200 SessionStatus"),
        "POST /v1/sessions/{name}/requests/{request_id}": (
            "JsonObject",
            "200 SessionStatus",
        ),
    }
    lines = schema["paths"]["/v1/sessions/{name}/output"]["get"]["parameters"][1]
    assert lines["schema"] == {
        "type": "integer",
        "minimum": 0,
        "default": 40,
        "title": "Lines",
    }


def test_a_caller_is_refused_before_its_body_is_read(
    service: Service, monkeypatch: pytest.MonkeyPatch
) -> None:
    def refuse(*_: Any) -> None:
        raise RunnerError("inside session x, which may not use the runner", 403)

    monkeypatch.setattr(Runner, "admit", refuse)
    with http(service) as c:
        for path in ("/v1/sessions", "/v1/sessions/ghost/send", "/v1/restart"):
            r = c.post(path, content=b"{name")
            assert (r.status_code, r.json()) == (
                403,
                {"error": "inside session x, which may not use the runner"},
            ), path
        # The schema isn't behind it: it says nothing api_types.py doesn't.
        assert c.get("/v1/openapi.json").status_code == 200


def test_a_body_is_json_whatever_its_content_type(service: Service) -> None:
    # curl -d sends application/x-www-form-urlencoded; the CLI's bodiless POSTs send none.
    service.start_session("s")
    with http(service) as c:
        for kind in ("application/x-www-form-urlencoded", "text/plain"):
            r = c.post(
                "/v1/sessions/s/stop",
                content=b'{"reason": "done"}',
                headers={"Content-Type": kind},
            )
            assert (r.status_code, r.json()["reason"]) == (200, "done"), kind
