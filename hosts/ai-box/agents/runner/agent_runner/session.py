"""A session: one agent process and its ACP session, its turns, and its state (README.md, "States")."""

from __future__ import annotations

import asyncio
import os
import time
from collections import deque
from collections.abc import Coroutine
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from . import acp
from .bus import EventBus
from .config import SETUP_SECONDS, AgentSpec, Config
from .errors import RunnerError
from .events import (
    ENDED,
    Body,
    Cancelled,
    Delivery,
    Event,
    Failed,
    Notified,
    Prompted,
    SessionOpened,
    State,
    StateChanged,
    TurnEnded,
    Updated,
)
from .handshake import Wanted, agent_env, handshake
from .inbox import Inbox
from .notify import Notifier, Outcome
from .parking import Parking
from .rpc import AgentExited, Connection, RpcError
from .store import Record, SessionFiles
from .updates import message_text
from .vendors import trust_folder


@dataclass(frozen=True)
class Services:
    """What every session shares: the agents, the event bus, and the way to tell Alex."""

    config: Config
    bus: EventBus
    notifier: Notifier


class Session(Inbox):
    def __init__(self, services: Services, record: Record, files: SessionFiles) -> None:
        self.services = services
        self.record = record
        self.files = files
        self.conn: Connection | None = None
        self.init = acp.InitializeResult()
        self.parking = Parking()
        self.queue: deque[str] = deque()
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
        return bool(self.conn and self.conn.running)

    @property
    def agent_session(self) -> str:
        assert self.record.agent_session_id, "the session has no agent session yet"
        return self.record.agent_session_id

    def save(self) -> None:
        self.record.updated_at = time.time()
        self.files.save(self.record)

    def emit(self, body: Body) -> Event:
        event = self.services.bus.publish(self.name, self.files, body)
        if isinstance(body, Updated):
            self.last_text += message_text(body.update)
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
        """running, waiting or idle, from what's open."""
        if self.record.state in ENDED or not self.alive:
            return
        if self.parking.open:
            self.set_state("waiting")
        elif self.turn and not self.turn.done():
            self.set_state("running")
        else:
            self.set_state("idle")

    async def fail(self, reason: str) -> None:
        """Failing loudly: the state says why, Alex is told, the agent ends."""
        self.set_state("failed", reason)
        self.emit(Failed(message=reason))
        self.services.notifier.notify(
            f"agent-runner: session {self.name} ({self.record.agent}) failed: {reason}",
            self.notified,
        )
        if self.conn:
            await self.conn.terminate()

    def notified(self, message: str, outcome: Outcome) -> None:
        self.emit(Notified(message=message, ok=outcome.ok, error=outcome.error))

    def explain(self, error: BaseException, doing: str) -> str:
        if isinstance(error, RpcError) and error.code == acp.AUTH_REQUIRED:
            said = self.last_text.strip()
            hint = f" ({said[:300]})" if said else ""
            return (
                f"the {self.record.agent} sign-in is missing or expired: {error}{hint}"
            )
        tail = self.conn.stderr_tail() if self.conn else ""
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
            except (RpcError, RunnerError, AgentExited, OSError, ValueError) as e:
                await self.fail(self.explain(e, "the agent couldn't start"))
                raise RunnerError(self.record.reason or str(e), 502) from e
            self.settle_state()

    async def _open(self, resume: str | None) -> None:
        spec, rec, config = self.spec, self.record, self.services.config
        if spec.claude_trust_file:
            trust_folder(Path(spec.claude_trust_file), rec.dir)
        self.files.folder.mkdir(parents=True, exist_ok=True)
        env = agent_env(rec.agent, spec, rec.env, config.refused_env, os.environ)
        self.conn = conn = await Connection.spawn(
            spec.command, rec.dir, env, self.files.agent_log
        )
        conn.on_message = self.on_message
        self.spawn(self.watch(conn))
        wanted = Wanted(
            agent=rec.agent,
            dir=rec.dir,
            resume=resume,
            mode=rec.mode,
            model=rec.model,
            meta=rec.session_meta,
        )
        opened = await handshake(conn, spec, wanted, self.mute, self.created)
        self.init = opened.init
        self.save()
        self.emit(
            SessionOpened(
                agent_session_id=opened.session_id,
                transcript=opened.transcript,
                agent_info=opened.init.agent_info,
            )
        )

    def mute(self, on: bool) -> None:
        self.muted = on

    def created(self, session_id: str, transcript: str | None) -> None:
        self.record.agent_session_id = session_id
        self.record.transcript = transcript

    async def watch(self, conn: Connection) -> None:
        code = await conn.closed
        if conn is not self.conn:
            return
        self.drop_pending("the agent exited")
        if self.stopping or self.record.state in ENDED:
            return
        if self.record.state == "starting":
            return  # open() reports it
        tail = f"(agent stderr: {conn.stderr_tail()})" if conn.stderr else ""
        await self.fail(f"the agent exited (code {code}) {tail}")

    # Prompts
    async def send(self, text: str) -> Delivery:
        """Hand the agent a message: a new turn, steered into the running one, or queued."""
        if self.record.state == "stopped":
            raise RunnerError(f"{self.name} is stopped", 409)
        if not self.alive:
            if not self.record.agent_session_id:
                raise RunnerError(
                    f"{self.name} never started, so there's nothing to resume", 409
                )
            await self.open(resume=self.record.agent_session_id)
        assert self.conn
        if self.turn and not self.turn.done():
            if self.init.steering:
                steered = await self.conn.request(
                    acp.SteeringResult,
                    "_session/steering",
                    acp.SteeringParams(self.agent_session, [acp.TextBlock(text)]),
                    SETUP_SECONDS,
                )
                if steered.outcome == "injected":
                    self.emit(Prompted(text=text, delivery="steered"))
                    return "steered"
            if self.turn and not self.turn.done():
                self.queue.append(text)
                self.emit(Prompted(text=text, delivery="queued"))
                return "queued"
        self.first_update.clear()
        self.turn = asyncio.create_task(self.run_turn(text))
        return "sent"

    async def run_turn(self, text: str) -> None:
        assert self.conn
        self.emit(Prompted(text=text, delivery="sent"))
        self.last_text = ""
        self.record.turns += 1
        self.settle_state()
        try:
            result = await self.conn.request(
                acp.PromptResult,
                "session/prompt",
                acp.PromptParams(self.agent_session, [acp.TextBlock(text)]),
                None,
            )
            self.emit(TurnEnded(stop_reason=result.stop_reason))
        except RpcError as e:
            if e.code == acp.AUTH_REQUIRED:
                await self.fail(self.explain(e, "the turn failed"))
                return
            self.emit(Failed(message=f"the turn failed: {e}"))
        except AgentExited:
            return  # watch() reports it
        finally:
            self.first_update.set()
            if self.turn is asyncio.current_task():
                self.turn = None
        self.settle_state()
        if self.queue and self.record.state not in ENDED:
            self.turn = asyncio.create_task(self.run_turn(self.queue.popleft()))

    async def cancel(self) -> None:
        """End the turn, cancel open requests, drop the queue; the agent stays up."""
        self.queue.clear()
        for request_id in list(self.parking.open):
            self.deliver(request_id, self.parking.cancel(request_id))
        if self.alive and self.record.agent_session_id:
            assert self.conn
            self.conn.notify("session/cancel", acp.CancelParams(self.agent_session))
            self.emit(Cancelled())

    async def stop(self, reason: str) -> None:
        self.stopping = True
        self.queue.clear()
        self.drop_pending("stopped")
        if self.conn:
            await self.conn.terminate()
        self.set_state("stopped", reason)

    async def go_offline(self, reason: str) -> None:
        """The runner stops: the agent ends, the session stays resumable."""
        if not self.alive:
            return
        assert self.conn
        self.stopping = True
        await self.conn.terminate()
        if self.record.state not in ENDED:
            self.set_state("offline", reason)
