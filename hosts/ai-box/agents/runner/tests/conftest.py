"""What the tests share: the runner's service in a thread, on a scratch socket and state folder,
with the stand-in agent (fake_acp_agent.py) as its agents."""

from __future__ import annotations

import asyncio
import json
import sys
import threading
import time
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

import pytest

# The package from this source tree, wherever pytest runs from (`just test` from the repository's
# root; the nix build from here).
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from agent_runner.client import Client, ClientError  # noqa: E402
from agent_runner.events import Event  # noqa: E402
from agent_runner.server import Settings, serve  # noqa: E402

FAKE = str(Path(__file__).with_name("fake_acp_agent.py"))


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


class Service:
    """The runner's service in a thread of its own."""

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

    @property
    def settings(self) -> Settings:
        notify = ["sh", "-c", f'printf "%s\\n" "$1" >> {self.notified}', "notify"]
        return Settings(self.socket, self.state, self.agents_file, notify)

    def start(self) -> None:
        loop = asyncio.new_event_loop()
        stop = asyncio.Event()
        self.loop, self.stop_event = loop, stop
        settings = self.settings

        def run() -> None:
            self.exit_code = loop.run_until_complete(serve(settings, stop))

        self.socket.unlink(missing_ok=True)
        self.thread = threading.Thread(target=run, daemon=True)
        self.thread.start()
        # The socket's file is there from its bind, a moment before the server listens.
        wait_for(self.answers)

    def answers(self) -> bool:
        try:
            self.client.agents()
        except ClientError:
            return False
        return True

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
        result: dict[str, Any] = wait_for(
            lambda: (s := self.status(name))["state"] in states and s
        )
        return result

    def events(self, name: str) -> list[dict[str, Any]]:
        stream = self.client.events(f"/v1/sessions/{name}/events?since=0")
        return [dict(e.encode_json()) for e in stream if isinstance(e, Event)]

    def agent_log(self) -> list[dict[str, Any]]:
        log = self.tmp / "fake.log"
        return [json.loads(line) for line in log.read_text().splitlines()]


AGENTS = {
    "steering": fake_agent(FAKE_STEERING="1"),
    "nosignin": fake_agent(FAKE_AUTH="fail-new"),
    "loadonly": fake_agent(FAKE_LOAD_ONLY="1"),
    "configmodel": fake_agent(FAKE_CONFIG_MODEL="1"),
    "token": {**fake_agent(), "pass_env": ["PASSED_TOKEN"]},
}


@pytest.fixture
def service(tmp_path: Path) -> Iterator[Service]:
    s = Service(
        tmp_path,
        {
            "default": "fake",
            "agents": {
                "fake": fake_agent(FAKE_LOG=str(tmp_path / "fake.log")),
                "auto": {
                    **fake_agent(),
                    "mode": "auto",
                    "claude_trust_file": str(tmp_path / "claude.json"),
                },
                **AGENTS,
            },
            "refused_env": ["ANTHROPIC_API_KEY"],
        },
    )
    s.start()
    yield s
    s.stop()
