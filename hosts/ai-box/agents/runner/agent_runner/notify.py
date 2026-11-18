"""Telling Alex a session failed: AGENT_RUNNER_NOTIFY (notify-alex), the message as last argument."""

from __future__ import annotations

import asyncio
import sys
from collections.abc import Callable, Sequence
from dataclasses import dataclass

from .config import NOTIFY_SECONDS


@dataclass(frozen=True)
class Outcome:
    ok: bool
    error: str | None = None


class Notifier:
    def __init__(self, command: Sequence[str], timeout: float = NOTIFY_SECONDS) -> None:
        self.command = list(command)
        self.timeout = timeout
        self.tasks: set[asyncio.Task[None]] = set()

    def notify(self, message: str, done: Callable[[str, Outcome], None]) -> None:
        """Print the message, and send it in the background; `done` gets it and the outcome."""
        print(message, file=sys.stderr, flush=True)
        if not self.command:
            return
        task = asyncio.create_task(self._send(message, done))
        self.tasks.add(task)
        task.add_done_callback(self.tasks.discard)

    async def _send(self, message: str, done: Callable[[str, Outcome], None]) -> None:
        outcome = await self.send(message)
        if not outcome.ok:
            print(f"agent-runner: notify failed: {outcome.error}", file=sys.stderr)
        done(message, outcome)

    async def send(self, message: str) -> Outcome:
        try:
            proc = await asyncio.create_subprocess_exec(
                *self.command,
                message,
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.PIPE,
            )
            try:
                _, err = await asyncio.wait_for(proc.communicate(), self.timeout)
            except TimeoutError:
                proc.kill()
                await proc.wait()
                raise
        except (OSError, TimeoutError) as e:
            return Outcome(False, repr(e))
        if proc.returncode:
            tail = err.decode(errors="replace").strip()[-500:]
            return Outcome(False, f"exit {proc.returncode}: {tail}")
        return Outcome(True)
