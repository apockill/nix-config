"""The runner: every session, by name. Starting one, the sessions from before a restart, shutdown."""

from __future__ import annotations

import asyncio
import contextlib
import re
import time
from pathlib import Path

from .api_types import SessionStatus, SessionSummary, StartRequest, public
from .bus import EventBus
from .config import AFTER_FIRST_UPDATE_SECONDS, FIRST_UPDATE_SECONDS, Config
from .errors import RunnerError
from .events import ENDED
from .notify import Notifier
from .session import Services, Session
from .store import Record, Store

NAME_PATTERN = re.compile(r"^[a-z0-9][a-z0-9-]{0,62}$")
ENV_NAME_PATTERN = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


class Runner:
    def __init__(self, config: Config, store: Store, notifier: Notifier) -> None:
        self.config = config
        self.store = store
        self.bus = EventBus()
        self.services = Services(config, self.bus, notifier)
        self.sessions: dict[str, Session] = {}

    def load(self) -> None:
        """The sessions from before this runner started: on record, and offline if they were up."""
        for record in self.store.load(time.time()):
            files = self.store.files(record.name)
            session = Session(self.services, record, files)
            seq, session.last_event_at = files.last_event()
            self.bus.advance(seq)
            self.sessions[record.name] = session
        # Only now, with seq past every logged event: these emit.
        for session in self.sessions.values():
            was = session.record.state
            if was not in ENDED and was != "offline":
                during = " during a turn" if was in ("running", "waiting") else ""
                session.set_state(
                    "offline", f"the runner restarted{during}; a message resumes it"
                )

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

    def summaries(self) -> list[SessionSummary]:
        """Every session, oldest first."""
        by_age = sorted(self.sessions.values(), key=lambda s: s.record.created_at)
        return [summary(s) for s in by_age]

    async def shutdown(self) -> None:
        for session in self.sessions.values():
            await session.go_offline("the runner stopped; a message resumes it")


def summary(session: Session) -> SessionSummary:
    return SessionSummary(
        **public(session.record),
        pending=len(session.parking.open),
        alive=session.alive,
        last_event_at=session.last_event_at,
    )


def status(session: Session) -> SessionStatus:
    return SessionStatus(
        **public(session.record),
        pending=[p.event for p in session.parking.open.values()],
        queued=list(session.queue),
        last_message=session.last_text,
        alive=session.alive,
        last_event_at=session.last_event_at,
    )
