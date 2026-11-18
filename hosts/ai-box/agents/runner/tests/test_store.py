"""Tests for store.py: records, event logs and retention on disk."""

from __future__ import annotations

import json
import os
import stat
from pathlib import Path
from typing import Any

import pytest
from agent_runner.config import KEEP_ENDED_SECONDS
from agent_runner.events import Event, Failed, StateChanged
from agent_runner.store import Record, SessionFiles, Store, write_private


def record(name: str = "job", **extra: Any) -> Record:
    return Record(name=name, agent="fake", dir="/w", created_at=1.0, **extra)


def test_write_private_replaces_the_file_for_its_owner_only(tmp_path: Path) -> None:
    path = tmp_path / "a" / "b.json"
    write_private(path, "one")
    write_private(path, "two")
    assert path.read_text() == "two"
    assert stat.S_IMODE(os.stat(path).st_mode) == 0o600
    assert os.listdir(path.parent) == ["b.json"]  # no temporary left behind


def test_a_record_saves_and_loads(tmp_path: Path) -> None:
    files = SessionFiles(tmp_path / "job")
    rec = record(env={"A": "secret"}, session_meta={"x": [1]}, state="idle", turns=2)
    files.save(rec)
    assert files.load() == rec
    on_disk = json.loads(files.record.read_text())
    assert on_disk["env"] == {"A": "secret"}  # the values are kept, for resumes
    assert stat.S_IMODE(os.stat(files.record).st_mode) == 0o600


def test_a_pre_split_record_loads(tmp_path: Path) -> None:
    files = SessionFiles(tmp_path / "job")
    files.folder.mkdir()
    old = {
        "name": "job",
        "agent": "claude",
        "dir": "/w",
        "created_at": 1795000000.0,
        "state": "offline",
        "reason": "the runner restarted; a message resumes it",
        "model": "haiku",
        "mode": None,
        "origin": "cc: Job",
        "env": {"PATH": "/bin"},
        "session_meta": None,
        "agent_session_id": "9c32",
        "transcript": "/t.jsonl",
        "title": None,
        "updated_at": 1795000042.5,
        "turns": 1,
    }
    files.record.write_text(json.dumps(old))
    loaded = files.load()
    assert loaded.agent_session_id == "9c32" and loaded.state == "offline"


def test_the_event_log(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    files = SessionFiles(tmp_path / "job")
    assert list(files.read_events()) == []
    assert files.last_event() == (0, 0.0)
    events = [Event(i, float(i), "job", StateChanged(state="idle")) for i in (1, 2, 3)]
    for event in events:
        files.append(event)
    with files.events.open("a") as f:
        f.write("not json\n")
    files.append(Event(4, 4.0, "job", Failed(message="x")))
    assert [e.seq for e in files.read_events()] == [1, 2, 3, 4]
    assert [e.seq for e in files.read_events(since=2)] == [3, 4]
    assert "events.jsonl:4: not an event" in capsys.readouterr().err
    assert files.last_event() == (4, 4.0)


def test_last_event_skips_a_torn_last_line(tmp_path: Path) -> None:
    files = SessionFiles(tmp_path / "job")
    files.append(Event(9, 9.5, "job", StateChanged(state="idle")))
    with files.events.open("a") as f:
        f.write('{"seq": 10, "ts"')
    assert files.last_event() == (9, 9.5)


def test_a_log_that_cannot_be_written_is_reported(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    (tmp_path / "file").write_text("")
    files = SessionFiles(tmp_path / "file" / "job")
    files.append(Event(1, 1.0, "job", StateChanged(state="idle")))
    assert "can't log an event of job" in capsys.readouterr().err


def test_load_keeps_live_and_recent_records_and_prunes_old_ended_ones(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    store = Store(tmp_path)
    assert store.load(0.0) == []
    now = 10 * KEEP_ENDED_SECONDS
    old = now - KEEP_ENDED_SECONDS - 1
    store.files("a-live").save(record("a-live", state="idle", updated_at=old))
    store.files("b-recent").save(
        record("b-recent", state="stopped", updated_at=now - 5)
    )
    store.files("c-old").save(record("c-old", state="failed", updated_at=old))
    bad = store.files("d-bad")
    bad.folder.mkdir()
    bad.record.write_text('{"name": 1}')
    names = [r.name for r in store.load(now)]
    assert names == ["a-live", "b-recent"]
    assert not store.files("c-old").folder.exists()
    assert "skipped" in capsys.readouterr().err
    store.remove("a-live")
    assert not store.files("a-live").folder.exists()
