"""The API's client, for the CLI: httpx on the runner's unix socket, answers as the API's models."""

from __future__ import annotations

import json
import urllib.parse
from collections.abc import Iterator
from typing import Any

import httpx
from pydantic import BaseModel, ValidationError

from .api_types import (
    AgentList,
    Output,
    Restarting,
    Sent,
    SessionList,
    SessionStatus,
    StartRequest,
)
from .base import JsonObject
from .events import Event, Heartbeat, decode_streamed


class ClientError(Exception):
    """The runner refused a call (its message), isn't running, or answered something odd."""

    def __init__(
        self, message: str, status: int = 0, resets_at: float | None = None
    ) -> None:
        super().__init__(message)
        # The HTTP status; 0 if the runner didn't answer.
        self.status = status
        # With a 429: when the usage limit resets (Unix seconds), if the agent said.
        self.resets_at = resets_at


def quote(part: str) -> str:
    return urllib.parse.quote(part, safe="")


def refusal(response: httpx.Response) -> ClientError:
    """The runner's error answer as a ClientError: its message, status and any reset time."""
    try:
        body = response.json()
    except ValueError:
        body = None
    body = body if isinstance(body, dict) else {}
    message = body.get("error")
    resets_at = body.get("resets_at")
    return ClientError(
        message if isinstance(message, str) else f"HTTP {response.status_code}",
        response.status_code,
        float(resets_at) if isinstance(resets_at, int | float) else None,
    )


class Client:
    def __init__(self, socket_path: str, timeout: float | None = 600) -> None:
        self.socket_path = socket_path
        self.http = httpx.Client(
            transport=httpx.HTTPTransport(uds=socket_path),
            base_url="http://agent-runner",
            timeout=timeout,
        )

    def _request(
        self, method: str, path: str, body: JsonObject | None = None
    ) -> httpx.Response:
        try:
            return self.http.request(method, path, json=body)
        except httpx.ConnectError as e:
            raise self.unreachable(e) from e
        except httpx.HTTPError as e:
            raise ClientError(
                f"can't reach the runner at {self.socket_path}: {e}"
            ) from e

    def unreachable(self, e: httpx.ConnectError) -> ClientError:
        """No socket, or nobody listening on it: not running. Anything else is said as it is."""
        cause: BaseException | None = e
        while cause is not None and not isinstance(cause, OSError):
            cause = (
                cause.__context__
            )  # httpx's error wraps httpcore's, which wraps the OSError
        if isinstance(cause, FileNotFoundError | ConnectionRefusedError):
            return ClientError(
                f"the runner isn't running ({self.socket_path}: {cause.strerror});"
                " check: systemctl --user status agent-runner"
            )
        return ClientError(f"can't reach the runner at {self.socket_path}: {e}")

    def call(self, method: str, path: str, body: JsonObject | None = None) -> Any:
        """One call; its answer as JSON. ClientError with the runner's message if it refused."""
        response = self._request(method, path, body)
        if response.status_code >= 300:
            raise refusal(response)
        try:
            return response.json()
        except ValueError as e:
            raise ClientError(f"the runner's answer isn't JSON: {e}") from e

    def typed[M: BaseModel](
        self, model: type[M], method: str, path: str, body: JsonObject | None = None
    ) -> M:
        data = self.call(method, path, body)
        try:
            return model.model_validate(data)
        except ValidationError as e:
            raise ClientError(f"the runner's answer to {path} doesn't fit: {e}") from e

    def events(self, path: str) -> Iterator[Event | Heartbeat]:
        try:
            with self.http.stream("GET", path, timeout=None) as response:
                if response.status_code >= 300:
                    response.read()
                    raise refusal(response)
                for line in response.iter_lines():
                    if line.strip():
                        yield decode_streamed(json.loads(line))
        except httpx.ConnectError as e:
            raise self.unreachable(e) from e
        except httpx.HTTPError as e:
            raise ClientError(f"the runner's event stream broke off: {e}") from e
        except (ValueError, ValidationError) as e:
            raise ClientError(f"the runner sent an odd event: {e}") from e

    # The calls (api_types.py)
    def agents(self) -> AgentList:
        return self.typed(AgentList, "GET", "/v1/agents")

    def sessions(self) -> SessionList:
        return self.typed(SessionList, "GET", "/v1/sessions")

    def status(self, name: str) -> SessionStatus:
        return self.typed(SessionStatus, "GET", f"/v1/sessions/{quote(name)}")

    def start(self, req: StartRequest) -> SessionStatus:
        body = req.model_dump(mode="json", exclude_none=True)
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

    def restart(self, force: bool = False) -> Restarting:
        body: JsonObject = {"force": True} if force else {}
        return self.typed(Restarting, "POST", "/v1/restart", body)
