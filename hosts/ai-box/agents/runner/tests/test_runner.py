"""runner.py: checking a start, the sessions from before a restart, and the list."""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

import pytest
from agent_runner.api_types import StartRequest
from agent_runner.config import KEEP_ENDED_SECONDS, Config
from agent_runner.errors import RunnerError
from agent_runner.events import Event, Prompted, State
from agent_runner.notify import Notifier
from agent_runner.runner import Runner
from agent_runner.store import Record, Store
from conftest import Service, fake_agent


def runner(tmp: Path) -> Runner:
    config = Config.model_validate(
        {
            "default": "fake",
            "agents": {"fake": fake_agent(), "other": fake_agent()},
            "refused_env": ["ANTHROPIC_API_KEY"],
        }
    )
    return Runner(config, Store(tmp / "state"), Notifier([]))


def start(tmp: Path, **fields: Any) -> StartRequest:
    return StartRequest.model_validate({"name": "job", "dir": str(tmp), **fields})


def test_check_gives_the_agent(tmp_path: Path) -> None:
    r = runner(tmp_path)
    assert r.check(start(tmp_path)) == "fake"
    assert r.check(start(tmp_path, agent="other", env={"OK_1": "x"})) == "other"
    assert r.check(start(tmp_path, name="a" * 63)) == "fake"


@pytest.mark.parametrize(
    "fields, error",
    [
        ({"name": "Bad Name"}, "name: lowercase letters"),
        ({"name": "-x"}, "name: lowercase letters"),
        ({"name": "a" * 64}, "name: lowercase letters"),
        ({"agent": "nobody"}, "agent must be one of fake, other"),
        ({"dir": "relative"}, "dir: an existing folder"),
        ({"dir": "/nonexistent"}, "dir: an existing folder"),
        ({"env": {"1X": "y"}}, "env: '1X' isn't a variable name"),
        ({"env": {"ANTHROPIC_API_KEY": "y"}}, "ANTHROPIC_API_KEY would switch"),
    ],
)
def test_check_refuses(tmp_path: Path, fields: dict[str, Any], error: str) -> None:
    with pytest.raises(RunnerError, match=error) as e:
        runner(tmp_path).check(start(tmp_path, **fields))
    assert e.value.status == 400


def test_check_refuses_a_name_with_a_newline(tmp_path: Path) -> None:
    with pytest.raises(RunnerError, match="name: lowercase letters"):
        runner(tmp_path).check(start(tmp_path, name="job\n"))


def on_disk(tmp: Path, name: str, state: State, updated_at: float, seq: int) -> None:
    files = Store(tmp / "state").files(name)
    files.save(
        Record(
            name=name,
            agent="fake",
            dir=str(tmp),
            created_at=updated_at,
            state=state,
            updated_at=updated_at,
        )
    )
    body = Prompted(text="x", delivery="sent")
    files.append(Event(seq=seq, ts=updated_at, session=name, body=body))


def test_load_puts_live_sessions_offline_and_continues_seq(tmp_path: Path) -> None:
    now = time.time()
    on_disk(tmp_path, "busy", "running", now, 7)
    on_disk(tmp_path, "quiet", "idle", now - 10, 3)
    on_disk(tmp_path, "done", "stopped", now - 5, 12)
    on_disk(tmp_path, "away", "offline", now - 4, 1)
    r = runner(tmp_path)
    r.load()
    assert sorted(r.sessions) == ["away", "busy", "done", "quiet"]
    states = {n: (s.record.state, s.record.reason) for n, s in r.sessions.items()}
    assert states == {
        "busy": (
            "offline",
            "the runner restarted during a turn; a message resumes it",
        ),
        "quiet": ("offline", "the runner restarted; a message resumes it"),
        "done": ("stopped", None),
        "away": ("offline", None),
    }
    # The new state events come after every logged one.
    assert r.bus.seq == 14
    assert [e.seq for e in r.sessions["quiet"].files.read_events()] == [3, 14]
    assert r.sessions["busy"].last_event_at > now
    assert r.sessions["away"].last_event_at == now - 4
    record = json.loads(r.sessions["busy"].files.record.read_text())
    assert record["state"] == "offline"
    assert [s.name for s in r.summaries()] == ["quiet", "done", "away", "busy"]


def test_load_deletes_long_ended_sessions(tmp_path: Path) -> None:
    old = time.time() - KEEP_ENDED_SECONDS - 60
    on_disk(tmp_path, "gone", "failed", old, 1)
    on_disk(tmp_path, "kept", "offline", old, 2)
    (tmp_path / "state/sessions/broken").mkdir()
    (tmp_path / "state/sessions/broken/session.json").write_text("{")
    r = runner(tmp_path)
    r.load()
    assert sorted(r.sessions) == ["kept"]
    assert not (tmp_path / "state/sessions/gone").exists()
    # A record that doesn't fit is skipped, not deleted.
    assert (tmp_path / "state/sessions/broken/session.json").exists()


def test_get(tmp_path: Path) -> None:
    with pytest.raises(RunnerError, match="no session named ghost") as e:
        runner(tmp_path).get("ghost")
    assert e.value.status == 404


def test_starting_over_an_ended_session_clears_its_folder(service: Service) -> None:
    service.start_session("s", "hello")
    service.wait_state("s", "idle")
    service.call("POST", "/v1/sessions/s/stop", {})
    first = service.events("s")
    service.start_session("s", "hello")
    service.wait_state("s", "idle")
    again = service.events("s")
    assert again[0]["seq"] > first[-1]["seq"]
    assert [e["kind"] for e in again].count("session") == 1


def test_summaries_are_oldest_first(service: Service) -> None:
    for name in ("b", "a", "c"):
        service.start_session(name)
    listed = service.call("GET", "/v1/sessions")["sessions"]
    assert [s["name"] for s in listed] == ["b", "a", "c"]
    assert all(s["pending"] == 0 and s["alive"] for s in listed)
    assert "queued" not in listed[0] and "last_message" not in listed[0]
