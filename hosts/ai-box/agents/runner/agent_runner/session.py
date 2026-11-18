"""A session: one agent process and its ACP session, its turns, and its state (README.md, "States")."""

from __future__ import annotations

import asyncio
import os
import time
from collections import defaultdict, deque
from collections.abc import Coroutine
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from acp.exceptions import RequestError
from acp.schema import InitializeResponse

from .agent import AUTH_REQUIRED, AgentExited, AgentProcess, agent_env
from .bus import EventBus
from .config import AgentSpec, Config
from .errors import RunnerError
from .events import (
    ENDED,
    Body,
    Event,
    Failed,
    Notified,
    PermissionAsked,
    SessionOpened,
    State,
    StateChanged,
)
from .limits import LimitNotices, active, describe
from .notify import Notifier, Outcome
from .opening import Wanted, open_session
from .parking import Parking
from .peers import Peers, marker
from .render import asked
from .store import Record, SessionFiles
from .turns import Turns
from .vendors import trust_folder


@dataclass(frozen=True)
class Services:
    """What every session shares: the agents, the event bus, the way to tell Alex (and what
    limits Alex has heard of), and who's calling (the runner's name for its sessions' marker).
    """

    config: Config
    bus: EventBus
    notifier: Notifier
    peers: Peers
    limit_notices: LimitNotices


class Session(Turns):
    def __init__(self, services: Services, record: Record, files: SessionFiles) -> None:
        self.services = services
        self.limit_notices = services.limit_notices
        self.record = record
        self.files = files
        self.agent: AgentProcess | None = None
        self.init: InitializeResponse | None = None
        self.parking = Parking()
        self.waiting = defaultdict(deque)
        self.turn: asyncio.Task[None] | None = None
        self.open_lock = asyncio.Lock()
        self.stopping = False
        # Set by the agent's first update or request after a prompt (start waits for it).
        self.first_update = asyncio.Event()
        # While session/load replays the conversation: history, not news.
        self.muted = False
        # The agent's text since the last prompt (status's last_message).
        self.last_text = ""
        # When the session's latest event happened: how long it has been quiet.
        self.last_event_at = 0.0
        self.tasks: set[asyncio.Task[None]] = set()

    @property
    def spec(self) -> AgentSpec:
        return self.services.config.agents[self.record.agent]

    @property
    def alive(self) -> bool:
        return bool(self.agent and self.agent.running)

    @property
    def agent_session(self) -> str:
        assert self.record.agent_session_id, "the session has no agent session yet"
        return self.record.agent_session_id

    def save(self) -> None:
        self.record.updated_at = time.time()
        self.files.save(self.record)

    def emit(self, body: Body) -> Event:
        event = self.services.bus.publish(self.name, self.files, body)
        self.last_event_at = event.ts
        return event

    def spawn(self, coro: Coroutine[Any, Any, None]) -> None:
        task = asyncio.create_task(coro)
        self.tasks.add(task)
        task.add_done_callback(self.tasks.discard)

    # State
    def set_state(self, state: State, reason: str | None = None) -> None:
        if self.record.state == state and self.record.reason == reason:
            return
        self.record.state = state
        self.record.reason = reason
        self.save()
        self.emit(StateChanged(state=state, reason=reason))

    def settle_state(self) -> None:
        """running, waiting, limited or idle, from what's open."""
        if self.record.state in ENDED or not self.alive:
            return
        if self.parking.open:
            self.set_state("waiting")
        elif self.turn and not self.turn.done():
            self.set_state("running")
        elif active(self.record.limit, time.time()):
            assert self.record.limit
            self.set_state("limited", describe(self.record.limit))
        else:
            self.set_state("idle")

    async def fail(self, reason: str) -> None:
        """Failing loudly: the state says why, Alex is told, the agent ends."""
        self.set_state("failed", reason)
        self.emit(Failed(message=reason))
        self.tell_alex(
            f"agent-runner: session {self.name} ({self.record.agent}) failed: {reason}"
        )
        if self.agent:
            await self.agent.terminate()

    def tell_alex(self, message: str) -> None:
        self.services.notifier.notify(message, self.notified)

    def notified(self, message: str, outcome: Outcome) -> None:
        self.emit(Notified(message=message, ok=outcome.ok, error=outcome.error))
        # A failure to tell stays in the record, where `agent list` and the daily digest see it.
        self.record.notify_error = None if outcome.ok else f"{outcome.error}"
        self.save()

    def parked(self, event: Event) -> None:
        """A request parked: Alex is told if nobody answers it in parked_notify_seconds."""
        self.spawn(self.unanswered(event, self.services.config.parked_notify_seconds))

    async def unanswered(self, event: Event, after: float) -> None:
        await asyncio.sleep(after)
        request_id, what = asked(event)
        if (
            request_id not in self.parking.open
            or self.parking.open[request_id].event != event
        ):
            return
        kind = "permission" if isinstance(event.body, PermissionAsked) else "question"
        self.tell_alex(
            f"agent-runner: session {self.name} has waited {duration(after)} for an answer"
            f" to its {kind} {request_id}: {what[:200]} (agent peek {self.name};"
            f" agent answer {self.name} {request_id} ...)"
        )

    def explain(self, error: BaseException, doing: str) -> str:
        if isinstance(error, RequestError) and error.code == AUTH_REQUIRED:
            said = self.last_text.strip()
            hint = f" ({said[:300]})" if said else ""
            return (
                f"the {self.record.agent} sign-in is missing or expired: {error}{hint}"
            )
        tail = self.agent.stderr_tail() if self.agent else ""
        return f"{doing}: {error}" + (f" (agent stderr: {tail})" if tail else "")

    # Connecting
    async def open(self, resume: str | None) -> None:
        """Start the agent and create (or resume) its session; `failed` with the reason if not."""
        async with self.open_lock:
            if self.alive:
                return
            self.set_state("starting")
            try:
                await self._open(resume)
            except (RequestError, RunnerError, AgentExited, OSError, ValueError) as e:
                await self.fail(self.explain(e, "the agent couldn't start"))
                raise RunnerError(self.record.reason or str(e), 502) from e
            self.settle_state()

    async def _open(self, resume: str | None) -> None:
        spec, rec, config = self.spec, self.record, self.services.config
        if spec.claude_trust_file:
            trust_folder(Path(spec.claude_trust_file), rec.dir)
        self.files.folder.mkdir(parents=True, exist_ok=True)
        env = agent_env(rec.agent, spec, rec.env, config.refused_env, os.environ)
        env.update(marker(rec.name, self.services.peers.runner))
        if spec.compact_window_env and (window := env.get(spec.compact_window_env)):
            rec.compact_window = int(window)
        self.waiting.clear()
        umask = int(config.agent_umask, 8) if config.agent_umask else None
        self.agent = agent = await AgentProcess.spawn(
            spec.command, rec.dir, env, self.files.agent_log, self, umask
        )
        self.spawn(self.watch(agent))
        wanted = Wanted(
            agent=rec.agent,
            dir=rec.dir,
            resume=resume,
            mode=rec.mode,
            model=rec.model,
            meta=rec.session_meta,
        )
        opened = await open_session(agent, spec, wanted, self.mute, self.created)
        self.init = opened.init
        self.save()
        info = opened.init.agent_info
        self.emit(
            SessionOpened(
                agent_session_id=opened.session_id,
                transcript=opened.transcript,
                agent_info=(
                    info.model_dump(mode="json", by_alias=True, exclude_none=True)
                    if info
                    else None
                ),
            )
        )

    def mute(self, on: bool) -> None:
        self.muted = on

    def created(self, session_id: str, transcript: str | None) -> None:
        self.record.agent_session_id = session_id
        self.record.transcript = transcript

    async def watch(self, agent: AgentProcess) -> None:
        code = await agent.closed
        if agent is not self.agent:
            return
        self.drop_pending("the agent exited")
        if self.stopping or self.record.state in ENDED:
            return
        if self.record.state == "starting":
            return  # open() reports it
        tail = f"(agent stderr: {agent.stderr_tail()})" if agent.stderr else ""
        await self.fail(f"the agent exited (code {code}) {tail}")

    async def stop(self, reason: str) -> None:
        self.stopping = True
        self.queue.clear()
        self.save()
        self.drop_pending("stopped")
        if self.agent:
            await self.agent.terminate()
        self.set_state("stopped", reason)

    async def go_offline(self, reason: str) -> None:
        """The runner stops: the agent ends, the session stays resumable."""
        if not self.agent or not self.alive:
            return
        self.stopping = True
        await self.agent.terminate()
        if self.record.state not in ENDED:
            self.set_state("offline", reason)


def duration(seconds: float) -> str:
    return f"{seconds / 60:.0f} min" if seconds >= 60 else f"{seconds:.0f} s"
