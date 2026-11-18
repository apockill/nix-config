"""Sessions on disk: AGENT_RUNNER_STATE/sessions/<name>/{session.json,events.jsonl,agent.log}.

`session.json` is the session's record (what the API reports and what a resume needs),
`events.jsonl` every event of the session, one per line, `agent.log` the agent's stderr.
"""

from __future__ import annotations

import contextlib
import json
import os
import shutil
import sys
import tempfile
from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path

from .config import KEEP_ENDED_SECONDS
from .events import ENDED, Event, State
from .schema import JsonObject, SchemaError, decode, encode


@dataclass(kw_only=True)
class Record:
    """A session's record (session.json)."""

    name: str
    agent: str
    dir: str
    created_at: float
    state: State = "starting"
    # Why the session is in its state, for failed, offline and stopped.
    reason: str | None = None
    model: str | None = None
    mode: str | None = None
    # Who started it: free text such as "job: <title>", "sculpt: <project>".
    origin: str | None = None
    # Extra environment for the agent, as given to `start` (kept for resumes).
    env: dict[str, str] = field(default_factory=dict)
    # `_meta` for session/new (vendor options, e.g. Claude's disallowed tools); kept for resumes.
    session_meta: JsonObject | None = None
    # The agent's own session id (resume with it) and its transcript of the session.
    agent_session_id: str | None = None
    transcript: str | None = None
    title: str | None = None
    updated_at: float = 0.0
    turns: int = 0


def write_private(path: Path, text: str) -> None:
    """Replace a file in one step, readable by its owner only."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.")
    with os.fdopen(fd, "w") as f:
        f.write(text)
    os.replace(tmp, path)


@dataclass(frozen=True)
class SessionFiles:
    """One session's folder."""

    folder: Path

    @property
    def record(self) -> Path:
        return self.folder / "session.json"

    @property
    def events(self) -> Path:
        return self.folder / "events.jsonl"

    @property
    def agent_log(self) -> Path:
        return self.folder / "agent.log"

    def save(self, record: Record) -> None:
        write_private(self.record, json.dumps(encode(record), indent=2) + "\n")

    def load(self) -> Record:
        """The record; OSError, ValueError (not JSON) or SchemaError (doesn't fit)."""
        return decode(Record, json.loads(self.record.read_text()))

    def append(self, event: Event) -> None:
        """Log an event; a failure is reported, not raised (the event still goes out live)."""
        line = json.dumps(event.encode_json(), ensure_ascii=False) + "\n"
        try:
            self.folder.mkdir(parents=True, exist_ok=True)
            with self.events.open("a") as f:
                f.write(line)
        except OSError as e:
            print(
                f"agent-runner: can't log an event of {event.session}: {e}",
                file=sys.stderr,
            )

    def read_events(self, since: int = 0) -> Iterator[Event]:
        """The logged events after `since`; a line that isn't an event is reported and skipped."""
        try:
            with self.events.open() as f:
                for number, line in enumerate(f, 1):
                    try:
                        event = Event.decode_json(json.loads(line))
                    except (ValueError, SchemaError) as e:
                        print(
                            f"agent-runner: {self.events}:{number}: not an event: {e}",
                            file=sys.stderr,
                        )
                        continue
                    if event.seq > since:
                        yield event
        except FileNotFoundError:
            return

    def last_event(self) -> tuple[int, float]:
        """The seq and time of the last logged event ((0, 0.0) if none)."""
        try:
            with self.events.open("rb") as f:
                f.seek(0, os.SEEK_END)
                f.seek(max(0, f.tell() - 65536))
                tail = f.read().splitlines()
        except OSError:
            return 0, 0.0
        for line in reversed(tail):
            with contextlib.suppress(ValueError, SchemaError):
                event = Event.decode_json(json.loads(line))
                return event.seq, event.ts
        return 0, 0.0


@dataclass(frozen=True)
class Store:
    """The state folder (AGENT_RUNNER_STATE)."""

    root: Path

    def files(self, name: str) -> SessionFiles:
        return SessionFiles(self.root / "sessions" / name)

    def remove(self, name: str) -> None:
        shutil.rmtree(self.files(name).folder, ignore_errors=True)

    def load(self, now: float) -> list[Record]:
        """Every record on disk, oldest name first; ended ones past retention are deleted."""
        sessions = self.root / "sessions"
        if not sessions.is_dir():
            return []
        records = []
        for path in sorted(sessions.glob("*/session.json")):
            files = SessionFiles(path.parent)
            try:
                record = files.load()
            except (OSError, ValueError) as e:  # SchemaError is a ValueError
                print(f"agent-runner: skipped {path}: {e}", file=sys.stderr)
                continue
            if record.state in ENDED and now - record.updated_at > KEEP_ENDED_SECONDS:
                shutil.rmtree(files.folder, ignore_errors=True)
                continue
            records.append(record)
        return records
