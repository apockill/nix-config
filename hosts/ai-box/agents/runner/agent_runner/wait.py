"""`agent wait`: block until a job needs its starter (Hermes runs it as a background waiter).

It returns (and the CLI exits 0, so a background waiter wakes its owner) when the job
  - prints a line that matches the marker               -> "MARKER <the line>"
  - waits for an answer (a permission or a question)    -> "WAITING", then the requests and the
                                                           last lines of its output
  - has been quiet for `idle` seconds with no turn running (a finished turn without a marker,
    a usage limit, an error)                            -> "IDLE (<state>, quiet <n>s)", then
                                                           the last lines
  - failed or was stopped, or isn't there               -> "ENDED <state>: <reason>",
                                                           "ENDED: no session <name>"
  - or the timeout passes                               -> "TIMEOUT"

The first word is the outcome. Prompts show in the output as "> ..." lines, so a marker named in
a brief or a message never starts a line; marker lines already there when it starts don't count.
"""

from __future__ import annotations

import math
import re
import time
from collections.abc import Callable
from dataclasses import dataclass, field

from .client import Client, ClientError
from .render import asked

# The done markers the briefs ask for: <PREFIX>-DONE, -NEED-LIVE, -RESTART-PLEASE.
DEFAULT_MARKER = r"^[A-Z][A-Z0-9-]*-(DONE|NEED-LIVE|RESTART-PLEASE)(:|\s*$)"
TIMEOUT_SECONDS = 4 * 3600.0
IDLE_SECONDS = 300.0
EVERY_SECONDS = 15.0
# How much output is searched for markers.
OUTPUT_LINES = 5000
WIDTH = 200


@dataclass(frozen=True, kw_only=True)
class Waiting:
    marker: re.Pattern[str] = re.compile(DEFAULT_MARKER)
    timeout: float = TIMEOUT_SECONDS
    idle: float = IDLE_SECONDS
    every: float = EVERY_SECONDS


@dataclass(frozen=True)
class Woken:
    """Why `wait` returned: the first line's first word, then what goes with it."""

    lines: list[str] = field(default_factory=list)

    @property
    def outcome(self) -> str:
        return self.lines[0].split()[0].rstrip(":") if self.lines else ""


@dataclass(frozen=True)
class Clock:
    monotonic: Callable[[], float] = time.monotonic
    now: Callable[[], float] = time.time
    sleep: Callable[[float], None] = time.sleep


def wait(client: Client, name: str, how: Waiting, clock: Clock | None = None) -> Woken:
    clock = clock or Clock()

    def output() -> list[str]:
        return client.output(name, OUTPUT_LINES).lines

    def markers(lines: list[str]) -> list[str]:
        return [line for line in lines if how.marker.search(line)]

    def cut(lines: list[str]) -> list[str]:
        return [line[:WIDTH] for line in lines]

    deadline = clock.monotonic() + how.timeout
    try:
        seen = len(markers(output()))
    except ClientError as e:
        if e.status == 404:
            return Woken([f"ENDED: no session {name}"])
        raise
    while clock.monotonic() < deadline:
        try:
            s = client.status(name)
        except ClientError as e:
            if e.status == 404:
                return Woken([f"ENDED: no session {name}"])
            raise
        if s.state in ("failed", "stopped"):
            return Woken([f"ENDED {s.state}: {s.reason or ''}"])
        if s.state == "waiting":
            asks = []
            for event in s.pending:
                request_id, what = asked(event)
                asks.append(f"{request_id} {event.kind}: {what}")
            return Woken(["WAITING", *asks, *cut(output()[-12:])])
        lines = output()
        found = markers(lines)
        if len(found) > seen:
            return Woken([f"MARKER {found[-1]}"])
        quiet = int(clock.now() - math.floor(s.last_event_at))
        if s.state not in ("running", "starting") and quiet >= how.idle:
            return Woken([f"IDLE ({s.state}, quiet {quiet}s)", *cut(lines[-8:])])
        clock.sleep(how.every)
    return Woken(["TIMEOUT"])
