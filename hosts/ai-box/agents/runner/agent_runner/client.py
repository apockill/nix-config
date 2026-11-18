"""The API's client, for the CLI: HTTP on the runner's unix socket, answers as typed bodies."""

from __future__ import annotations

import http.client
import json
import socket
import urllib.parse
from collections.abc import Iterator

from .api_types import (
    AgentList,
    Output,
    Restarting,
    Sent,
    SessionList,
    SessionStatus,
    StartRequest,
)
from .events import Event, Heartbeat, decode_streamed
from .schema import JsonObject, JsonValue, SchemaError, decode, encode_object


class ClientError(Exception):
    """The runner refused a call (its message), isn't running, or answered something odd."""

    def __init__(self, message: str, status: int = 0) -> None:
        super().__init__(message)
        self.status = status


class UnixHTTPConnection(http.client.HTTPConnection):
    def __init__(self, path: str, timeout: float | None = None) -> None:
        super().__init__("agent-runner", timeout=timeout)
        self.socket_path = path

    def connect(self) -> None:
        self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.sock.settimeout(self.timeout)
        self.sock.connect(self.socket_path)


def quote(part: str) -> str:
    return urllib.parse.quote(part, safe="")


class Client:
    def __init__(self, socket_path: str) -> None:
        self.socket_path = socket_path

    def _open(
        self,
        method: str,
        path: str,
        body: JsonValue = None,
        timeout: float | None = 600,
    ) -> http.client.HTTPResponse:
        conn = UnixHTTPConnection(self.socket_path, timeout=timeout)
        data = json.dumps(body).encode() if body is not None else None
        headers = {"Content-Type": "application/json"} if data is not None else {}
        try:
            conn.request(method, path, body=data, headers=headers)
            return conn.getresponse()
        except (FileNotFoundError, ConnectionRefusedError) as e:
            raise ClientError(
                f"the runner isn't running ({self.socket_path}: {e.strerror});"
                " check: systemctl --user status agent-runner"
            ) from e
        except OSError as e:
            raise ClientError(
                f"can't reach the runner at {self.socket_path}: {e}"
            ) from e

    def call(self, method: str, path: str, body: JsonValue = None) -> JsonValue:
        """One call; its answer as JSON. ClientError with the runner's message if it refused."""
        resp = self._open(method, path, body)
        data = self._json(resp.read())
        if resp.status >= 300:
            raise ClientError(error_of(data, resp.status), resp.status)
        return data

    def typed[T](
        self, cls: type[T], method: str, path: str, body: JsonValue = None
    ) -> T:
        data = self.call(method, path, body)
        try:
            return decode(cls, data)
        except SchemaError as e:
            raise ClientError(f"the runner's answer to {path} doesn't fit: {e}") from e

    @staticmethod
    def _json(raw: bytes) -> JsonValue:
        try:
            value: JsonValue = json.loads(raw or b"{}")
        except ValueError as e:
            raise ClientError(f"the runner's answer isn't JSON: {e}") from e
        return value

    def events(self, path: str) -> Iterator[Event | Heartbeat]:
        resp = self._open("GET", path, timeout=None)
        if resp.status >= 300:
            raise ClientError(
                error_of(self._json(resp.read()), resp.status), resp.status
            )
        while line := resp.readline():
            if line.strip():
                try:
                    yield decode_streamed(self._json(line))
                except SchemaError as e:
                    raise ClientError(f"the runner sent an odd event: {e}") from e

    # The calls (README.md)
    def agents(self) -> AgentList:
        return self.typed(AgentList, "GET", "/v1/agents")

    def sessions(self) -> SessionList:
        return self.typed(SessionList, "GET", "/v1/sessions")

    def status(self, name: str) -> SessionStatus:
        return self.typed(SessionStatus, "GET", f"/v1/sessions/{quote(name)}")

    def start(self, req: StartRequest) -> SessionStatus:
        body: JsonObject = {
            k: v for k, v in encode_object(req).items() if v is not None
        }
        return self.typed(SessionStatus, "POST", "/v1/sessions", body)

    def send(self, name: str, text: str) -> Sent:
        return self.typed(
            Sent, "POST", f"/v1/sessions/{quote(name)}/send", {"text": text}
        )

    def output(self, name: str, lines: int) -> Output:
        return self.typed(
            Output, "GET", f"/v1/sessions/{quote(name)}/output?lines={lines}"
        )

    def cancel(self, name: str) -> SessionStatus:
        return self.typed(
            SessionStatus, "POST", f"/v1/sessions/{quote(name)}/cancel", {}
        )

    def stop(self, name: str, reason: str | None = None) -> SessionStatus:
        body: JsonObject = {"reason": reason} if reason else {}
        return self.typed(
            SessionStatus, "POST", f"/v1/sessions/{quote(name)}/stop", body
        )

    def answer(self, name: str, request_id: str, body: JsonObject) -> SessionStatus:
        path = f"/v1/sessions/{quote(name)}/requests/{quote(request_id)}"
        return self.typed(SessionStatus, "POST", path, body)

    def restart(self) -> Restarting:
        return self.typed(Restarting, "POST", "/v1/restart", {})


def error_of(data: JsonValue, status: int) -> str:
    message = data.get("error") if isinstance(data, dict) else None
    return message if isinstance(message, str) else f"HTTP {status}"
