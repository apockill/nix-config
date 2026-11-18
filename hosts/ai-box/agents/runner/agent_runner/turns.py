"""A session's turns: sending a message (a new turn, steered into the running one, or queued),
running a turn, how it fails, and cancelling. A part of `Session`.

A turn that fails is an `error` event with the agent's own error kind and data. A usage limit
(limits.py) makes the session `limited` until the reset, and Alex is told once per reset; other
failures are told once they repeat (REPEATED_FAILURES in a row). Queued messages are in the
session's record, so a runner restart doesn't lose them, and they go before a newer message.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Coroutine
from typing import Any

from acp.exceptions import RequestError
from acp.schema import InitializeResponse

from .agent import AUTH_REQUIRED, AgentExited, AgentProcess
from .config import REPEATED_FAILURES, SETUP_SECONDS
from .errors import RunnerError
from .events import Cancelled, Delivery, Failed, Prompted, TurnEnded
from .inbox import Inbox
from .limits import LimitNotices, active, describe, limit_of, turn_error
from .store import Limit
from .vendors import STEERING, SteeringResult, steering, steers


class Turns(Inbox):
    """A session's turns (Session's base: these use its state)."""

    agent: AgentProcess | None
    init: InitializeResponse | None
    turn: asyncio.Task[None] | None
    limit_notices: LimitNotices

    @property
    def alive(self) -> bool:
        raise NotImplementedError

    @property
    def agent_session(self) -> str:
        raise NotImplementedError

    def tell_alex(self, message: str) -> None:
        raise NotImplementedError

    def spawn(self, coro: Coroutine[Any, Any, None]) -> None:
        raise NotImplementedError

    async def open(self, resume: str | None) -> None:
        raise NotImplementedError

    async def fail(self, reason: str) -> None:
        raise NotImplementedError

    def explain(self, error: BaseException, doing: str) -> str:
        raise NotImplementedError

    @property
    def queue(self) -> list[str]:
        return self.record.queued

    async def send(self, text: str) -> Delivery:
        """Hand the agent a message: a new turn, steered into the running one, or queued."""
        if self.record.state == "stopped":
            raise RunnerError(f"{self.name} is stopped", 409)
        if (limit := self.record.limit) and active(limit, time.time()):
            if limit.resets_at is not None:
                raise RunnerError(
                    f"{self.name} hit the {describe(limit)}; send again after that",
                    429,
                    limit.resets_at,
                )
        if not self.alive:
            if not self.record.agent_session_id:
                raise RunnerError(
                    f"{self.name} never started, so there's nothing to resume", 409
                )
            await self.open(resume=self.record.agent_session_id)
        assert self.agent and self.init
        if self.turn and not self.turn.done():
            if steers(self.init):
                raw = await self.agent.extension(
                    STEERING, steering(self.agent_session, text), SETUP_SECONDS
                )
                if SteeringResult.model_validate(raw or {}).outcome == "injected":
                    self.emit(Prompted(text=text, delivery="steered"))
                    return "steered"
            if self.turn and not self.turn.done():
                return self.enqueue(text)
        if self.queue:
            # Messages queued before (a turn that failed, the agent or the runner restarted)
            # go first, in order.
            delivery = self.enqueue(text)
            self.next_turn()
            return delivery
        self.start_turn(text)
        return "sent"

    def enqueue(self, text: str) -> Delivery:
        self.queue.append(text)
        self.save()
        self.emit(Prompted(text=text, delivery="queued"))
        return "queued"

    def start_turn(self, text: str) -> None:
        self.first_update.clear()
        self.turn = asyncio.create_task(self.run_turn(text))

    def next_turn(self) -> None:
        """The oldest queued message, as a new turn."""
        text = self.queue.pop(0)
        self.save()
        self.start_turn(text)

    async def run_turn(self, text: str) -> None:
        assert self.agent
        self.emit(Prompted(text=text, delivery="sent"))
        self.last_text = ""
        self.record.turns += 1
        self.settle_state()
        try:
            result = await self.agent.prompt(self.agent_session, text)
            self.ended_well(result.stop_reason)
        except RequestError as e:
            if e.code == AUTH_REQUIRED:
                await self.fail(self.explain(e, "the turn failed"))
                return
            self.turn_failed(f"the turn failed: {e}", e.data)
        except RunnerError as e:
            self.turn_failed(f"the turn failed: {e}", None)
        except AgentExited:
            return  # watch() reports it
        finally:
            self.first_update.set()
            if self.turn is asyncio.current_task():
                self.turn = None
        self.settle_state()
        if self.queue and self.record.state in ("idle", "running"):
            self.next_turn()

    def ended_well(self, stop_reason: str | None) -> None:
        self.record.limit = None
        self.record.failed_turns = 0
        self.save()
        self.emit(TurnEnded(stop_reason=stop_reason))

    def turn_failed(self, message: str, data: Any) -> None:
        """An error event with the agent's error kind and data; a limit, or a repeat, is told."""
        kind = turn_error(data)
        self.emit(Failed(message=message, error_kind=kind.error_kind, data=data))
        if limit := limit_of(kind):
            self.limited(limit)
            return
        self.record.failed_turns += 1
        self.save()
        if self.record.failed_turns == REPEATED_FAILURES:
            self.tell_alex(
                f"agent-runner: session {self.name} ({self.record.agent}): its last"
                f" {REPEATED_FAILURES} turns failed; the last: {message[:300]}"
            )

    def limited(self, limit: Limit) -> None:
        """The account's usage limit: `limited` until it resets (then `idle` again by itself);
        queued messages stay queued. Alex hears of it once per reset."""
        self.record.limit = limit
        self.save()
        now = time.time()
        if self.limit_notices.first(self.record.agent, limit, now):
            queued = f"; {len(self.queue)} queued messages wait" if self.queue else ""
            self.tell_alex(
                f"agent-runner: {self.record.agent} hit its {describe(limit)}: session"
                f" {self.name} is limited (sends are refused until then){queued}"
            )
        if limit.resets_at is not None:
            self.spawn(self.limit_ends(limit, limit.resets_at - now))

    async def limit_ends(self, limit: Limit, after: float) -> None:
        await asyncio.sleep(max(0.0, after))
        if self.record.limit == limit and not (self.turn and not self.turn.done()):
            self.settle_state()

    async def cancel(self) -> None:
        """End the turn, cancel open requests, drop the queue; the agent stays up."""
        self.queue.clear()
        self.save()
        for request_id in list(self.parking.open):
            self.resolved(request_id, self.parking.cancel(request_id))
        if self.agent and self.alive and self.record.agent_session_id:
            await self.agent.cancel(self.agent_session)
            self.emit(Cancelled())
