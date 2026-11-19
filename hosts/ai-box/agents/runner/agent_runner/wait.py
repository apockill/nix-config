"""`agent wait`: block until a job needs its starter (Hermes runs it as a background waiter).

It returns (and the CLI exits 0, so a background waiter wakes its owner) when the job
  - waits for an answer (a permission or a question)    -> "WAITING", then the requests and the
                                                           last lines of its output
  - has printed a line that matches the marker since    -> "MARKER <the line>"
    its last prompt (before the waiter started too)
  - hit the account's usage limit                       -> "LIMITED <resets_at> <what>", then the
                                                           last lines (resets_at: Unix seconds,
                                                           or "unknown")
  - has been quiet for `idle` seconds with no turn running (a finished turn without a marker,
    an error, the runner restarted)                     -> "IDLE (<state>, quiet <n>s)", then
                                                           the last lines
  - failed or was stopped, or isn't there               -> "ENDED <state>: <reason>",
                                                           "ENDED: no session <name>"
  - or the timeout passes                               -> "TIMEOUT after <n>s: <name> is still
                                                           <state>; ..." (nobody watches it now)

The first word is the outcome. A marker counts from the session's last prompt (a message sent or
steered in), so one printed before the waiter started counts, and one from an earlier turn
doesn't; prompts themselves are never searched. The runner restarting doesn't end the waiter: it
reconnects for up to 120 s (RECONNECT_SECONDS).
"""

from __future__ import annotations

import math
import re
import time
import urllib.parse
from collections.abc import Callable
from dataclasses import dataclass, field

from .client import Client, ClientError
from .events import Event, Prompted
from .limits import active, describe
from .render import asked, render

# The done markers the briefs ask for: <PREFIX>-DONE, -NEED-LIVE, -RESTART-PLEASE.
DEFAULT_MARKER = r"^[A-Z][A-Z0-9-]*-(DONE|NEED-LIVE|RESTART-PLEASE)(:|\s*$)"
TIMEOUT_SECONDS = 4 * 3600.0
IDLE_SECONDS = 300.0
EVERY_SECONDS = 15.0
# How long the runner may be unreachable (a restart takes seconds) before the waiter gives up.
RECONNECT_SECONDS = 120.0
WIDTH = 200


@dataclass(frozen=True, kw_only=True)
class Waiting:
    marker: re.Pattern[str] = re.compile(DEFAULT_MARKER)
    timeout: float = TIMEOUT_SECONDS
    idle: float = IDLE_SECONDS
    every: float = EVERY_SECONDS
    reconnect: float = RECONNECT_SECONDS


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


class Turn:
    """The session's events since its last prompt (the prompt included), read as they come."""

    def __init__(self, client: Client, name: str) -> None:
        self.path = f"/v1/sessions/{urllib.parse.quote(name, safe='')}/events"
        self.client = client
        self.seq = 0
        self.events: list[Event] = []

    def read(self) -> None:
        for event in self.client.events(f"{self.path}?since={self.seq}"):
            if not isinstance(event, Event):
                continue
            self.seq = max(self.seq, event.seq)
            body = event.body
            if isinstance(body, Prompted) and body.delivery != "queued":
                self.events = []
            self.events.append(event)

    def markers(self, marker: re.Pattern[str]) -> list[str]:
        said = render(e for e in self.events if not isinstance(e.body, Prompted))
        return [line for line in said if marker.search(line)]

    def last(self, lines: int) -> list[str]:
        return [line[:WIDTH] for line in render(self.events)[-lines:]]


def wait(client: Client, name: str, how: Waiting, clock: Clock | None = None) -> Woken:
    clock = clock or Clock()
    deadline = clock.monotonic() + how.timeout
    turn = Turn(client, name)
    gone_since: float | None = None
    state = "?"
    while True:
        try:
            woken, state = check(client, name, turn, how, clock)
        except ClientError as e:
            if e.status == 404:
                return Woken([f"ENDED: no session {name}"])
            if e.status:
                raise
            # Not reachable: the runner restarting, most likely.
            gone_since = gone_since if gone_since is not None else clock.monotonic()
            if clock.monotonic() - gone_since > how.reconnect:
                raise ClientError(f"{e} (for over {how.reconnect:.0f} s)") from e
            woken = None
        else:
            gone_since = None
        if woken:
            return woken
        if clock.monotonic() >= deadline:
            return Woken(
                [
                    f"TIMEOUT after {how.timeout:.0f}s: {name} is still {state}; nothing"
                    f" watches it now: run `agent wait {name}` again, or `agent stop {name}`"
                ]
            )
        clock.sleep(how.every)


def check(
    client: Client, name: str, turn: Turn, how: Waiting, clock: Clock
) -> tuple[Woken | None, str]:
    """One look at the session: why to wake, if there is one, and its state."""
    s = client.status(name)
    if s.state in ("failed", "stopped"):
        return Woken([f"ENDED {s.state}: {s.reason or ''}"]), s.state
    turn.read()
    if s.state == "waiting":
        asks = []
        for event in s.pending:
            request_id, what = asked(event)
            asks.append(f"{request_id} {event.kind}: {what}")
        return Woken(["WAITING", *asks, *turn.last(12)]), s.state
    if found := turn.markers(how.marker):
        return Woken([f"MARKER {found[-1]}"]), s.state
    # Limited, or offline (the runner restarted) with the limit still on: sends are refused.
    if s.state in ("limited", "offline") and active(s.limit, clock.now()):
        assert s.limit
        resets = f"{s.limit.resets_at:.0f}" if s.limit.resets_at else "unknown"
        return Woken([f"LIMITED {resets} {describe(s.limit)}", *turn.last(8)]), s.state
    quiet = int(clock.now() - math.floor(s.last_event_at))
    if s.state not in ("running", "starting") and quiet >= how.idle:
        return Woken([f"IDLE ({s.state}, quiet {quiet}s)", *turn.last(8)]), s.state
    return None, s.state
