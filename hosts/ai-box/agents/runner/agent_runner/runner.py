"""The runner: every session, by name. Starting one, the sessions from before a restart, shutdown."""

from __future__ import annotations

import asyncio
import contextlib
import os
import re
import time
from pathlib import Path

from .api_types import SessionStatus, SessionSummary, StartRequest, public
from .bus import EventBus
from .config import AFTER_FIRST_UPDATE_SECONDS, FIRST_UPDATE_SECONDS, Config
from .errors import RunnerError
from .events import ENDED
from .limits import LimitNotices, describe
from .notify import Notifier, Outcome
from .peers import Caller, Peers, admit
from .session import Services, Session
from .store import Record, Store

NAME_PATTERN = re.compile(r"^[a-z0-9][a-z0-9-]{0,62}$")
ENV_NAME_PATTERN = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


# The states in which a restart loses work: a turn running, a request waiting for its answer.
BUSY = ("starting", "running", "waiting")
# How long a stopping runner waits for its last notices (systemd's TimeoutStopSec is 30 s).
SHUTDOWN_NOTIFY_SECONDS = 10.0


class Runner:
    def __init__(
        self, config: Config, store: Store, notifier: Notifier, peers: Peers
    ) -> None:
        self.config = config
        self.store = store
        self.bus = EventBus()
        self.notifier = notifier
        self.services = Services(config, self.bus, notifier, peers, LimitNotices())
        self.sessions: dict[str, Session] = {}

    def load(self) -> None:
        """The sessions from before this runner started: on record, and offline if they were up.
        Alex is told of turns the restart cut short, and of records that can't be read (those
        stay, as failed sessions, until a start reuses the name)."""
        records, unreadable = self.store.load(time.time())
        for record in records:
            files = self.store.files(record.name)
            session = Session(self.services, record, files)
            seq, session.last_event_at = files.last_event()
            self.bus.advance(seq)
            self.sessions[record.name] = session
        for broken in unreadable:
            files = self.store.files(broken.name)
            reason = f"its session.json can't be read: {broken.error}"
            record = Record(
                name=broken.name,
                agent=self.config.default_agent,
                dir="/",
                created_at=0.0,
                state="failed",
                reason=reason,
            )
            session = Session(self.services, record, files)
            seq, session.last_event_at = files.last_event()
            self.bus.advance(seq)
            self.sessions[broken.name] = session
            self.notifier.notify(
                f"agent-runner: session {broken.name}: {reason}", ignore
            )
        # Only now, with seq past every logged event: these emit.
        cut = []
        for session in self.sessions.values():
            was = session.record.state
            if was not in ENDED and was != "offline":
                during = " during a turn" if was in BUSY else ""
                if during:
                    cut.append(session.name)
                session.set_state(
                    "offline", f"the runner restarted{during}; a message resumes it"
                )
        if cut:
            names = ", ".join(cut)
            self.notifier.notify(
                f"agent-runner: the runner restarted during the turns of {names}; they're"
                " offline, and a message to each resumes it (its last turn is cut short)",
                ignore,
            )

    def caller(self, pid: int) -> Caller:
        agents = {
            s.agent.pid: name
            for name, s in self.sessions.items()
            if s.agent and s.alive
        }
        return self.services.peers.identify(pid, agents, os.getpid())

    def admit(self, pid: int | None) -> Caller:
        """The caller, if it may use the runner; RunnerError 403 if it's inside a session that
        may not (peers.py)."""
        if pid is None:
            raise RunnerError("refused: the runner can't tell who is calling", 403)
        caller = self.caller(pid)
        allowed = {name: s.record.allow_runner for name, s in self.sessions.items()}
        admit(caller, allowed)
        return caller

    def busy(self) -> list[str]:
        return [
            n for n, s in self.sessions.items() if s.alive and s.record.state in BUSY
        ]

    def get(self, name: str) -> Session:
        session = self.sessions.get(name)
        if session is None:
            raise RunnerError(f"no session named {name}", 404)
        return session

    def check(self, req: StartRequest) -> str:
        """What the schema can't say about a start; the agent it gets."""
        if not NAME_PATTERN.fullmatch(req.name):
            raise RunnerError(
                "name: lowercase letters, digits and dashes, starting with a letter or digit"
                " (`agent start` makes one from a title)"
            )
        agent = req.agent or self.config.default_agent
        if agent not in self.config.agents:
            raise RunnerError(
                f"agent must be one of {', '.join(sorted(self.config.agents))}"
            )
        if not Path(req.dir).is_absolute() or not Path(req.dir).is_dir():
            raise RunnerError("dir: an existing folder, as an absolute path")
        for key in req.env or {}:
            if not ENV_NAME_PATTERN.fullmatch(key):
                raise RunnerError(f"env: {key!r} isn't a variable name")
            if key in self.config.refused_env:
                raise RunnerError(
                    f"env: {key} would switch the agent off its subscription; refused"
                )
        window = self.config.agents[agent].compact_window_env
        if (
            window
            and window in (req.env or {})
            and not (req.env or {})[window].isdigit()
        ):
            raise RunnerError(f"env: {window} must be a whole number of tokens")
        return agent

    async def start(self, req: StartRequest) -> Session:
        agent = self.check(req)
        if old := self.sessions.get(req.name):
            if old.record.state not in ENDED:
                raise RunnerError(
                    f"a session named {req.name} is {old.record.state}; stop it first",
                    409,
                )
            self.store.remove(req.name)
        record = Record(
            name=req.name,
            agent=agent,
            dir=str(Path(req.dir).resolve()),
            created_at=time.time(),
            model=req.model,
            mode=req.mode,
            origin=req.origin,
            env=dict(req.env or {}),
            session_meta=req.session_meta,
            allow_runner=bool(req.allow_runner),
        )
        session = Session(self.services, record, self.store.files(req.name))
        self.sessions[req.name] = session
        session.save()
        await session.open(resume=req.resume)
        if req.task:
            await session.send(req.task)
            await self.first_signs(session)
        return session

    @staticmethod
    async def first_signs(session: Session) -> None:
        """Wait for the agent's first sign of life after the task, so a sign-in it checks only
        on its first request fails the start, not later. Claude says so in a message just
        before the error, so the error gets a moment after it."""
        with contextlib.suppress(TimeoutError):
            await asyncio.wait_for(session.first_update.wait(), FIRST_UPDATE_SECONDS)
            if session.turn and not session.turn.done():
                await asyncio.wait_for(
                    asyncio.shield(session.turn), AFTER_FIRST_UPDATE_SECONDS
                )
        if session.record.state == "failed":
            raise RunnerError(session.record.reason or "failed", 502)
        if session.record.state == "limited" and (limit := session.record.limit):
            raise RunnerError(
                f"{session.name} hit the {describe(limit)}, so its task didn't run; the"
                " session stays: send it a message after that, or stop it",
                429,
                limit.resets_at,
            )

    def summaries(self) -> list[SessionSummary]:
        """Every session, oldest first."""
        by_age = sorted(self.sessions.values(), key=lambda s: s.record.created_at)
        return [summary(s) for s in by_age]

    async def shutdown(self) -> None:
        """Every agent ends; sessions stay resumable. Alex is told of turns this cuts short
        (here when the runner stops; at the next start when it didn't get to)."""
        if busy := self.busy():
            self.notifier.notify(
                f"agent-runner: the runner stopped during the turns of {', '.join(busy)};"
                " they're offline, and a message to each resumes it (its last turn is cut"
                " short)",
                ignore,
            )
        for name, session in self.sessions.items():
            during = " during a turn" if name in busy else ""
            await session.go_offline(
                f"the runner stopped{during}; a message resumes it"
            )
            for task in list(session.tasks):
                task.cancel()
        await self.notifier.drain(SHUTDOWN_NOTIFY_SECONDS)


def ignore(_message: str, _outcome: Outcome) -> None:
    """For a notice that belongs to no session: its outcome is on stderr (notify.py)."""


def summary(session: Session) -> SessionSummary:
    return SessionSummary.model_validate(
        {
            **public(session.record),
            "pending": len(session.parking.open),
            "alive": session.alive,
            "last_event_at": session.last_event_at,
        }
    )


def status(session: Session) -> SessionStatus:
    return SessionStatus.model_validate(
        {
            **public(session.record),
            "pending": [p.event for p in session.parking.open.values()],
            "last_message": session.last_text,
            "alive": session.alive,
            "last_event_at": session.last_event_at,
        }
    )
