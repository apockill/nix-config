"""`agent kanban-lane`: the Hermes kanban cards assigned to `coder`, worked as runner jobs.

The runner's one coupling to Hermes; nix-config's hosts/ai-box/hermes/card-lane runs it as the user
service card-lane, and its build runs this module's tests against Hermes's own CLI. Hermes's
dispatcher starts no worker for a `coder` card (`skipped_nonspawnable`) and keeps the rest of the
board: runs, comments, taking back a claim that ran out, notifications. The lane talks to the board
only through the `hermes kanban` CLI. Every POLL_SECONDS it claims each ready `coder` card and
works it in a thread; when it starts, it takes back the `coder` cards still running. Each change it
makes names the card's run, so a run the board has taken back can't be changed. Working a card:
start its session (card-<id>) on the lane's agent with the card's context, or hand that session the
latest context (an answer, a retry), then wait on it (wait.py), heartbeating the card on each wake:

  the job prints CARD-DONE: <summary>        -> complete with the summary, stop the session
  it asks (a question, a permission) or prints CARD-NEED-LIVE / -RESTART-PLEASE
                                             -> block (needs_input) with what it asks
  it hits a usage limit                      -> a comment; wait for the reset, then carry on
  ... one that resets after the claim runs out
                                             -> block (transient): usage limit until <time>
  it goes quiet without a marker or ends, or the runner or board refuses
                                             -> block (transient) with its last words

The board sees no process of the lane's, so it takes a card back only when its claim runs out
(CLAIM_SECONDS, a day from the claim; a heartbeat doesn't extend it): a card whose lane is gone, or
one worked for longer, goes back to ready, a failure booked.
"""

from __future__ import annotations

import contextlib
import json
import os
import re
import subprocess
import sys
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, NoReturn

from .client import Client, ClientError
from .jobs import JobError, JobSpec, answer_body, slug, start_request
from .render import asked
from .wait import Waiting, Woken, wait

LANE = "coder"
CLAIM_SECONDS = 86400
POLL_SECONDS = 30.0
MARKER = r"^CARD-(DONE|NEED-LIVE|RESTART-PLEASE)(:|\s*$)"
# A wake at least this often heartbeats the card, so the board shows it's being worked.
HEARTBEAT_SECONDS = 1800.0
# How long to wait out a usage limit whose reset time the agent didn't give.
LIMIT_SECONDS = 3600.0
sleep = time.sleep

BRIEF = """\
You're working card {card} of Hermes's kanban board on ai-box. The card, its parents' results \
and its comments:

{context}

Work in this folder. The board is kept for you: don't change this card with `hermes kanban`. \
When you're done, print one line `CARD-DONE: <what you did, for the card>`. If you need Alex (a \
decision, hardware, a restart), ask him, or print `CARD-NEED-LIVE: <what you need>`: the card \
waits for him."""
RETRY = """\
Card {card} is back with you. Its current context, comments included:

{context}

Carry on from where you are, and finish with `CARD-DONE: <what you did>`."""
CARRY_ON = (
    "The usage limit has reset. Carry on, and finish with `CARD-DONE: <what you did>`."
)


class BoardError(Exception):
    """`hermes kanban` refused or failed; the message has its output."""


class Blocked(Exception):
    """The lane blocked the card: its run is over."""


def kanban(hermes: str, *args: str, env: dict[str, str] | None = None) -> str:
    done = subprocess.run(
        [hermes, "kanban", *args],
        capture_output=True,
        text=True,
        env={**os.environ, **(env or {})},
        check=False,
    )
    if done.returncode:
        raise BoardError(f"hermes kanban {args[0]}: {done.stdout}{done.stderr}")
    return done.stdout


def cards(hermes: str, status: str) -> list[str]:
    listed = kanban(hermes, "list", "--assignee", LANE, "--status", status, "--json")
    return [str(card["id"]) for card in json.loads(listed)]


@dataclass(frozen=True)
class Board:
    """One card's run, through `hermes kanban`."""

    hermes: str
    card: str
    run: str
    workspace: str
    # When the claim runs out (Unix seconds); a heartbeat doesn't move it.
    expires: float

    def call(self, *args: str) -> str:
        scope = {"HERMES_KANBAN_TASK": self.card, "HERMES_KANBAN_RUN_ID": self.run}
        return kanban(self.hermes, *args, env=scope)

    def context(self) -> str:
        return self.call("context", self.card).strip()

    def heartbeat(self, note: str) -> None:
        self.call("heartbeat", self.card, f"--note={note}")

    def comment(self, text: str) -> None:
        self.call("comment", self.card, "--", text)

    def complete(self, summary: str) -> None:
        self.call("complete", self.card, f"--summary={summary}")

    def block(self, kind: str, reason: str) -> None:
        self.call("block", self.card, "--kind", kind, "--", reason)


def take(hermes: str, card: str, claim: bool = True) -> Board:
    """The card's run: claimed now, or (claim=False) the one the lane already holds."""
    if claim:
        kanban(hermes, "claim", card, f"--ttl={CLAIM_SECONDS}")
    shown: dict[str, Any] = json.loads(kanban(hermes, "show", card, "--json"))
    runs = [r for r in shown["runs"] if r["status"] == "running"]
    if not runs:
        raise BoardError(f"{card} has no running run")
    run = runs[-1]
    workspace = str(shown["task"]["workspace_path"])
    expires = float(run["started_at"]) + CLAIM_SECONDS
    return Board(hermes, card, str(run["id"]), workspace, expires)


def begin(
    client: Client,
    board: Board,
    name: str,
    agent: str | None,
    adopted: bool,
) -> None:
    """Start the card's session, or hand the same one the card's latest context. A card the
    lane takes back (adopted) keeps its session as it is."""
    try:
        s = client.status(name)
    except ClientError as e:
        if e.status != 404:
            raise
        s = None
    if s is None or s.state == "stopped":
        spec = JobSpec(
            title=f"card {board.card}",
            dir=board.workspace,
            task=BRIEF.format(card=board.card, context=board.context()),
            agent=agent,
            origin=f"kanban card {board.card}",
        )
        client.start(start_request(spec, os.environ))
        return
    if adopted:
        return
    # Its open questions blocked the card; their answers are in the card's comments.
    for event in s.pending:
        request_id, _ = asked(event)
        client.answer(name, request_id, answer_body(request_id, None, False, True))
    client.send(name, RETRY.format(card=board.card, context=board.context()))


def waiting_out(board: Board, call: Callable[[], object]) -> None:
    """call(), after waiting out each usage limit it hits; the card stays claimed meanwhile."""
    while True:
        try:
            call()
            return
        except ClientError as e:
            if e.status != 429:
                raise
            pause(board, str(e), e.resets_at)


def pause(board: Board, said: str, resets_at: float | None) -> None:
    """Wait out a usage limit with the card claimed, or block the card (Blocked) when the limit
    resets after the claim runs out."""
    until = resets_at or time.time() + LIMIT_SECONDS
    if until >= board.expires:
        at = time.strftime("%Y-%m-%d %H:%M", time.localtime(until))
        board.block("transient", f"usage limit until {at}: {said}")
        raise Blocked
    at = time.strftime("%H:%M", time.localtime(until))
    board.comment(f"usage limit, carrying on at {at}: {said}")
    sleep(max(0.0, until - time.time()))


def settle(client: Client, board: Board, name: str, woken: Woken) -> bool:
    """What a wake means for the card; False to wait again."""
    said = "\n".join(woken.lines[1:])[-2000:]
    match woken.outcome:
        case "TIMEOUT":
            return False
        case "LIMITED":
            resets_at = woken.lines[0].split()[1]
            pause(board, said, float(resets_at) if resets_at.isdigit() else None)
            waiting_out(board, lambda: client.send(name, CARRY_ON))
            return False
        case "MARKER":
            line = woken.lines[0].removeprefix("MARKER ")
            if line.startswith("CARD-DONE"):
                summary = line.removeprefix("CARD-DONE").lstrip(": ")
                board.complete(summary or client.status(name).last_message or "done")
                client.stop(name, "card done")
            else:
                board.block("needs_input", line)
        case "WAITING":
            board.block("needs_input", f"the job asks:\n{said}")
        case _:
            stopped = f"the job stopped without CARD-DONE ({woken.lines[0]})"
            board.block("transient", f"{stopped}:\n{said}")
    return True


def work(
    client: Client,
    board: Board,
    agent: str | None,
    adopted: bool = False,
    how: Waiting | None = None,
) -> None:
    """Work the card until its run ends: done, blocked, or the lane couldn't go on."""
    how = how or Waiting(marker=re.compile(MARKER), timeout=HEARTBEAT_SECONDS)
    name = slug(f"card {board.card}")
    try:
        waiting_out(board, lambda: begin(client, board, name, agent, adopted))
        while True:
            woken = wait(client, name, how)
            board.heartbeat(woken.outcome)
            if settle(client, board, name, woken):
                return
    except Blocked:
        return
    except (ClientError, BoardError, JobError) as e:
        print(f"agent kanban-lane: card {board.card}: {e}", file=sys.stderr, flush=True)
        with contextlib.suppress(BoardError):
            board.block("transient", f"the lane stopped: {e}")


@dataclass
class Lane:
    client: Client
    hermes: str
    agent: str | None
    how: Waiting | None = None
    working: dict[str, threading.Thread] = field(default_factory=dict)

    def tick(self, status: str = "ready") -> list[threading.Thread]:
        """Take the lane's cards in `status` that no thread works; their threads."""
        started = []
        for card in cards(self.hermes, status):
            if (t := self.working.get(card)) and t.is_alive():
                continue
            try:
                board = take(self.hermes, card, claim=status == "ready")
            except BoardError as e:  # another claim won, most likely
                print(f"agent kanban-lane: {e}", file=sys.stderr, flush=True)
                continue
            client = Client(self.client.socket_path)  # the thread's own connections
            args = (client, board, self.agent, status != "ready", self.how)
            t = threading.Thread(target=work, args=args, name=card, daemon=True)
            t.start()
            started.append(t)
            self.working[card] = t
        return started

    def run(self, every: float = POLL_SECONDS) -> NoReturn:
        status = "running"
        while True:
            try:
                self.tick(status)
                status = "ready"
            except BoardError as e:
                print(f"agent kanban-lane: {e}", file=sys.stderr, flush=True)
            time.sleep(every)
