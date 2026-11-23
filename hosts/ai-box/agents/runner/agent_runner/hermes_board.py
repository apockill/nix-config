"""`agent kanban-worker`: a Hermes kanban card worked as a runner job.

The runner's one coupling to Hermes; the plugin that spawns it is nix-config's
hosts/ai-box/hermes/card-worker, whose contract check fails the build when a Hermes release
changes what this relies on. Hermes's dispatcher spawns this for a card assigned to `coder`, with
the card's run in the environment (HERMES_KANBAN_TASK, _RUN_ID, _CLAIM_LOCK, _WORKSPACE, _DB), and
keeps the board: claims, heartbeat windows, reclaim, retries, the failure breaker, notifications.
This process holds the run and talks to the board only through the public `hermes kanban` CLI. It
starts the card's session (card-<id>) on the configured agent with the card's context, or on a
retry sends the latest context to the same session, then waits on it (wait.py) and heartbeats on
each wake:

  the job prints CARD-DONE: <summary>        -> complete with the summary, stop the session, 0
  it asks (a question, a permission) or prints CARD-NEED-LIVE / -RESTART-PLEASE
                                             -> block (needs_input) with what it asks, 0
  it hits the usage limit                    -> 75: Hermes requeues it without booking a failure
  it goes quiet without a marker or ends, or the runner or board refuses
                                             -> 1: a crash; Hermes retries, and blocks the card
                                                after 2 in a row
"""

from __future__ import annotations

import re
import subprocess
import sys
from collections.abc import Mapping
from dataclasses import dataclass

from .client import Client, ClientError
from .jobs import JobSpec, answer_body, slug, start_request
from .render import asked
from .wait import Waiting, Woken, wait

# Hermes's worker exit contract (hermes_cli.kanban_db, hermes_cli.quiet_single_query).
RATE_LIMITED = 75
CRASHED = 1
EXIT_TRAILER = "[kanban-worker-exit] rc="
MARKER = r"^CARD-(DONE|NEED-LIVE|RESTART-PLEASE)(:|\s*$)"
# A wake at least this often heartbeats the card: Hermes extends a live worker's claim only while
# its last heartbeat is under an hour old.
HEARTBEAT_SECONDS = 1800.0

BRIEF = """\
You're working card {card} of Hermes's kanban board on ai-box. The card, its parents' results \
and its comments:

{context}

Work in this folder. The board is kept for you: don't change this card with `hermes kanban`. \
When you're done, print one line `CARD-DONE: <what you did, for the card>`. If you need Alex (a \
decision, hardware, a restart), ask him, or print `CARD-NEED-LIVE: <what you need>`: the card \
waits for him."""
RETRY = """\
Hermes retried card {card}. Its current context, comments included:

{context}

Carry on from where you are, and finish with `CARD-DONE: <what you did>`."""


class BoardError(Exception):
    """`hermes kanban` refused or failed; the message has its output."""


@dataclass(frozen=True)
class Board:
    """The card, through `hermes kanban`; the environment carries the run's grant."""

    hermes: str
    card: str

    def run(self, *args: str) -> str:
        done = subprocess.run(
            [self.hermes, "kanban", *args], capture_output=True, text=True, check=False
        )
        if done.returncode:
            raise BoardError(f"hermes kanban {args[0]}: {done.stdout}{done.stderr}")
        return done.stdout

    def context(self) -> str:
        return self.run("context", self.card).strip()

    def heartbeat(self, note: str) -> None:
        self.run("heartbeat", self.card, f"--note={note}")

    def comment(self, text: str) -> None:
        self.run("comment", self.card, "--", text)

    def complete(self, summary: str) -> None:
        self.run("complete", self.card, f"--summary={summary}")

    def block(self, reason: str) -> None:
        self.run("block", self.card, "--kind", "needs_input", "--", reason)


def begin(
    client: Client, board: Board, name: str, spec: JobSpec, env: Mapping[str, str]
) -> None:
    """Start the card's session, or on a retry hand the same one the card's latest context."""
    try:
        s = client.status(name)
    except ClientError as e:
        if e.status != 404:
            raise
        s = None
    if s is None or s.state == "stopped":
        client.start(start_request(spec, env))
        return
    # Its open questions blocked the card; their answers are in the card's comments.
    for event in s.pending:
        request_id, _ = asked(event)
        client.answer(name, request_id, answer_body(request_id, None, False, True))
    client.send(name, RETRY.format(card=board.card, context=board.context()))


def report(client: Client, board: Board, name: str, woken: Woken) -> int | None:
    """What a wake means for the card; None to wait again."""
    said = "\n".join(woken.lines[1:])[-2000:]
    match woken.outcome:
        case "TIMEOUT":
            return None
        case "MARKER":
            line = woken.lines[0].removeprefix("MARKER ")
            if line.startswith("CARD-DONE"):
                summary = line.removeprefix("CARD-DONE").lstrip(": ")
                board.complete(summary or client.status(name).last_message or "done")
                client.stop(name, "card done")
            else:
                board.block(line)
            return 0
        case "WAITING":
            board.block(f"the job asks:\n{said}")
            return 0
        case "LIMITED":
            board.comment(f"usage limit: {woken.lines[0]}")
            return RATE_LIMITED
    board.comment(f"the job stopped without CARD-DONE ({woken.lines[0]}):\n{said}")
    return CRASHED


def work(
    client: Client,
    board: Board,
    env: Mapping[str, str],
    agent: str | None,
    model: str | None,
    how: Waiting | None = None,
) -> int:
    how = how or Waiting(marker=re.compile(MARKER), timeout=HEARTBEAT_SECONDS)
    title = f"card {board.card}"
    name = slug(title)
    try:
        brief = BRIEF.format(card=board.card, context=board.context())
        spec = JobSpec(
            title=title,
            dir=env["HERMES_KANBAN_WORKSPACE"],
            task=brief,
            agent=agent,
            model=model,
            origin=f"kanban card {board.card}",
        )
        begin(client, board, name, spec, env)
        while True:
            woken = wait(client, name, how)
            board.heartbeat(woken.outcome)
            if (code := report(client, board, name, woken)) is not None:
                return code
    except ClientError as e:
        print(f"agent kanban-worker: {e}", file=sys.stderr)
        return RATE_LIMITED if e.status == 429 else CRASHED
    except (BoardError, KeyError) as e:
        print(f"agent kanban-worker: {e}", file=sys.stderr)
        return CRASHED


def main(
    client: Client,
    env: Mapping[str, str],
    agent: str | None,
    model: str | None,
    hermes: str,
) -> int:
    if card := env.get("HERMES_KANBAN_TASK"):
        code = work(client, Board(hermes, card), env, agent, model)
    else:
        print(
            "agent kanban-worker: no HERMES_KANBAN_TASK (Hermes's dispatcher runs this)"
        )
        code = CRASHED
    # Read from the worker log when the dispatcher can't reap this process (a gateway restart).
    print(f"{EXIT_TRAILER}{code}", flush=True)
    return code
