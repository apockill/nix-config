"""http_io.py: reading a request off the socket, and writing answers."""

from __future__ import annotations

import asyncio
import json
from typing import cast

import pytest
from agent_runner.errors import RunnerError
from agent_runner.http_io import (
    Malformed,
    Request,
    json_line,
    read_request,
    start_stream,
    write_json,
)


def read(raw: bytes) -> Request:
    async def go() -> Request:
        reader = asyncio.StreamReader()
        reader.feed_data(raw)
        reader.feed_eof()
        return await read_request(reader)

    return asyncio.run(go())


class Sink:
    """Stands in for a StreamWriter: keeps what's written."""

    def __init__(self) -> None:
        self.data = b""

    def write(self, data: bytes) -> None:
        self.data += data


def test_a_request_with_a_body() -> None:
    body = json.dumps({"text": "hé"}).encode()
    req = read(
        b"POST /v1/sessions/a%20b/send?lines=5&follow=1 HTTP/1.1\r\n"
        b"Host: runner\r\nContent-Type: application/json\r\n"
        b"Content-Length: " + str(len(body)).encode() + b"\r\n\r\n" + body
    )
    assert req.method == "POST"
    assert req.path == "/v1/sessions/a b/send"
    assert req.parts == ["v1", "sessions", "a b", "send"]
    assert req.query == {"lines": "5", "follow": "1"}
    assert req.body == {"text": "hé"}


def test_no_body_is_an_empty_object() -> None:
    req = read(b"GET /v1/sessions HTTP/1.1\r\nHost: x\r\n\r\n")
    assert req.body == {} and req.query == {}


def test_a_body_that_isnt_json() -> None:
    with pytest.raises(RunnerError, match="the body isn't JSON") as e:
        read(b"POST /v1/x HTTP/1.1\r\nContent-Length: 1\r\n\r\n{")
    assert e.value.status == 400


@pytest.mark.parametrize(
    "raw",
    [
        b"GET /v1/x HTTP/1.1\r\n",  # no end of the head
        b"GARBAGE\r\n\r\n",  # no method, target, version
        b"POST /v1/x HTTP/1.1\r\nContent-Length: 10\r\n\r\n{}",  # short body
        b"POST /v1/x HTTP/1.1\r\nContent-Length: ten\r\n\r\n",
    ],
)
def test_not_a_request(raw: bytes) -> None:
    with pytest.raises(Malformed):
        read(raw)


def test_query_parameters() -> None:
    req = Request("GET", "/v1/x", {"lines": "12", "empty": "", "bad": "-1"}, {})
    assert req.int_param("lines", 40) == 12
    assert req.int_param("missing", 40) == 40
    assert req.int_param("empty", 7) == 7
    with pytest.raises(RunnerError, match="bad: a whole number, not '-1'"):
        req.int_param("bad", 0)
    for value, on in (("1", True), ("true", True), ("yes", True), ("0", False)):
        assert Request("GET", "/", {"follow": value}, {}).flag("follow") is on
    assert not req.flag("follow")


def test_answers() -> None:
    assert json_line({"a": "é"}) == '{"a": "é"}\n'.encode()
    sink = Sink()
    write_json(cast(asyncio.StreamWriter, sink), 404, {"error": "no"})
    head, body = sink.data.split(b"\r\n\r\n")
    assert head.split(b"\r\n") == [
        b"HTTP/1.1 404 Not Found",
        b"Content-Type: application/json",
        f"Content-Length: {len(body)}".encode(),
        b"Connection: close",
    ]
    assert json.loads(body) == {"error": "no"}
    sink = Sink()
    write_json(cast(asyncio.StreamWriter, sink), 299, {})
    assert sink.data.startswith(b"HTTP/1.1 299 OK\r\n")
    sink = Sink()
    start_stream(cast(asyncio.StreamWriter, sink))
    assert sink.data == (
        b"HTTP/1.1 200 OK\r\nContent-Type: application/x-ndjson\r\n"
        b"Connection: close\r\n\r\n"
    )
