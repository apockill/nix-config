"""HTTP/1.1 on the unix socket, as much as the API needs: one request per connection, JSON bodies,
JSON answers or a stream of JSON lines (NDJSON)."""

from __future__ import annotations

import asyncio
import json
import urllib.parse
from dataclasses import dataclass

from .errors import RunnerError
from .schema import JsonValue

REASONS = {
    200: "OK",
    201: "Created",
    400: "Bad Request",
    404: "Not Found",
    405: "Method Not Allowed",
    409: "Conflict",
    500: "Internal Server Error",
    502: "Bad Gateway",
    504: "Gateway Timeout",
}


class Malformed(Exception):
    """Not an HTTP request: the connection is closed without an answer."""


@dataclass(frozen=True)
class Request:
    method: str
    path: str
    query: dict[str, str]
    body: JsonValue

    @property
    def parts(self) -> list[str]:
        return [p for p in self.path.split("/") if p]

    def int_param(self, name: str, default: int) -> int:
        value = self.query.get(name)
        if value is None or value == "":
            return default
        if not value.isdigit():
            raise RunnerError(f"{name}: a whole number, not {value!r}")
        return int(value)

    def flag(self, name: str) -> bool:
        return self.query.get(name) in ("1", "true", "yes")


async def read_request(reader: asyncio.StreamReader) -> Request:
    """The next request; Malformed if it isn't one, RunnerError if its body isn't JSON."""
    try:
        head = await reader.readuntil(b"\r\n\r\n")
        lines = head.decode("latin-1").split("\r\n")
        method, target, _ = lines[0].split(" ", 2)
        headers = {}
        for line in lines[1:]:
            if ":" in line:
                key, value = line.split(":", 1)
                headers[key.strip().lower()] = value.strip()
        length = int(headers.get("content-length") or 0)
        raw = await reader.readexactly(length) if length else b""
    except (asyncio.IncompleteReadError, asyncio.LimitOverrunError, ValueError) as e:
        raise Malformed(str(e)) from e
    url = urllib.parse.urlsplit(target)
    query = dict(urllib.parse.parse_qsl(url.query))
    path = urllib.parse.unquote(url.path)
    try:
        body: JsonValue = json.loads(raw) if raw else {}
    except ValueError as e:
        raise RunnerError(f"the body isn't JSON: {e}") from e
    return Request(method, path, query, body)


def json_line(value: JsonValue) -> bytes:
    return json.dumps(value, ensure_ascii=False).encode() + b"\n"


def write_json(writer: asyncio.StreamWriter, status: int, body: JsonValue) -> None:
    data = json_line(body)
    writer.write(
        f"HTTP/1.1 {status} {REASONS.get(status, 'OK')}\r\n"
        "Content-Type: application/json\r\n"
        f"Content-Length: {len(data)}\r\nConnection: close\r\n\r\n".encode() + data
    )


def start_stream(writer: asyncio.StreamWriter) -> None:
    """The head of an NDJSON answer; its lines follow until the connection closes."""
    writer.write(
        b"HTTP/1.1 200 OK\r\nContent-Type: application/x-ndjson\r\nConnection: close\r\n\r\n"
    )
