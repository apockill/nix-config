"""The canary's own agent runner (canary.py): `agent serve` on a socket and state of its own in a
temp folder, nobody notified, its API spoken over HTTP on that socket."""

from __future__ import annotations

import http.client
import json
import socket
import subprocess
import time
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from evidence import TURN_SECONDS, CanaryError


class UnixHTTPConnection(http.client.HTTPConnection):
    def __init__(self, path: str, timeout: float) -> None:
        super().__init__("agent-runner", timeout=timeout)
        self.socket_path = path

    def connect(self) -> None:
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        sock.settimeout(self.timeout)
        sock.connect(self.socket_path)
        self.sock = sock


class Runner:
    """`agent serve` with its own socket and state; the API spoken over HTTP on the socket."""

    def __init__(self, agent: str, folder: Path, env: Mapping[str, str]) -> None:
        self.agent = agent
        self.folder = folder
        self.socket = folder / "sock"
        self.env = {
            **env,
            "AGENT_RUNNER_SOCKET": str(self.socket),
            "AGENT_RUNNER_STATE": str(folder / "state"),
            "AGENT_RUNNER_NOTIFY": "",
        }
        self.proc: subprocess.Popen[bytes] | None = None

    def start(self) -> None:
        log = (self.folder / "serve.log").open("ab")
        self.proc = subprocess.Popen(
            [self.agent, "serve"], env=self.env, stdout=log, stderr=log, cwd=self.folder
        )
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            if self.proc.poll() is not None:
                raise CanaryError(
                    f"the private runner exited with {self.proc.returncode}"
                )
            try:
                self.call("GET", "/v1/agents")
                return
            except OSError:
                time.sleep(0.3)
        raise CanaryError("the private runner didn't answer within 30 s")

    def restart(self) -> int:
        """POST /v1/restart, as `agent restart` does; the exit code, then a new runner."""
        assert self.proc
        self.call("POST", "/v1/restart", {})
        code = self.proc.wait(timeout=60)
        self.start()
        return code

    def stop(self) -> None:
        if self.proc and self.proc.poll() is None:
            self.proc.terminate()
            try:
                self.proc.wait(timeout=60)
            except subprocess.TimeoutExpired:
                self.proc.kill()

    def call(
        self, method: str, path: str, body: Any = None, timeout: float = 600
    ) -> Any:
        conn = UnixHTTPConnection(str(self.socket), timeout)
        try:
            data = None if body is None else json.dumps(body).encode()
            headers = {"Content-Type": "application/json"} if data is not None else {}
            conn.request(method, path, body=data, headers=headers)
            response = conn.getresponse()
            raw = response.read()
        finally:
            conn.close()
        if response.status >= 300:
            raise CanaryError(f"{method} {path}: {response.status} {raw[:300]!r}")
        if path.endswith("/events") or "/events?" in path:
            return [json.loads(line) for line in raw.splitlines() if line.strip()]
        return json.loads(raw) if raw else None

    def events(self, name: str) -> list[dict[str, Any]]:
        result: list[dict[str, Any]] = self.call(
            "GET", f"/v1/sessions/{name}/events?since=0"
        )
        return result

    def wait_turn(self, name: str, since: int) -> dict[str, Any]:
        """Until a turn ended (or failed, or a request parked) after event `since`: that event."""
        deadline = time.monotonic() + TURN_SECONDS
        while time.monotonic() < deadline:
            for e in self.events(name):
                if e["seq"] > since and e["kind"] in ("turn_end", "error", "question"):
                    return e
                if e["seq"] > since and e["kind"] == "state" and e["state"] == "failed":
                    raise CanaryError(f"{name} failed: {e.get('reason')}")
            time.sleep(1)
        raise CanaryError(f"{name}: no turn end within {TURN_SECONDS:.0f} s")

    def latest(self, name: str) -> int:
        return max((e["seq"] for e in self.events(name)), default=0)

    def turn(self, name: str, text: str) -> dict[str, Any]:
        since = self.latest(name)
        self.call("POST", f"/v1/sessions/{name}/send", {"text": text})
        return self.wait_turn(name, since)
