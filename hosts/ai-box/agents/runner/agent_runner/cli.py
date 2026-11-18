"""`agent`: the coding agents' sessions and jobs, from a shell (README.md, "CLI").

Each verb is a call or two of the API, plus the job layer (jobs.py): names from titles, the task
file as the first message, and `wait`.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from collections.abc import Sequence
from typing import NoReturn

from .api_types import SessionStatus
from .base import JsonObject
from .client import Client, ClientError, quote
from .jobs import JobError, JobSpec, answer_body, read_task, start_request
from .limits import describe
from .render import asked
from .wait import Waiting, wait


class Parser(argparse.ArgumentParser):
    def error(self, message: str) -> NoReturn:
        self.print_usage(sys.stderr)
        self.exit(2, f"{self.prog.split()[0]}: {message}\n")


def env_arg(value: str) -> tuple[str, str]:
    if "=" not in value:
        raise argparse.ArgumentTypeError(f"--env takes NAME=value, not {value!r}")
    key, val = value.split("=", 1)
    return key, val


def meta_arg(value: str) -> JsonObject:
    try:
        meta = json.loads(value)
    except ValueError as e:
        raise argparse.ArgumentTypeError(f"--session-meta isn't JSON: {e}") from e
    if not isinstance(meta, dict):
        raise argparse.ArgumentTypeError("--session-meta takes a JSON object")
    return meta


def parser(prog: str) -> Parser:
    p = Parser(
        prog=prog, description="The coding agents' sessions (agents/runner/README.md)."
    )
    sub = p.add_subparsers(dest="verb", required=True, parser_class=Parser)
    sub.add_parser("serve", help="run the service (agent-runner.service)")
    s = sub.add_parser("start", help="start a job: a session named after its title")
    s.add_argument("title", help="the job's title; the session's name is made from it")
    s.add_argument("dir", help="the folder it works in")
    s.add_argument("task_file", nargs="?", help="its first message, from this file")
    s.add_argument("--task", help="its first message (instead of a task file)")
    s.add_argument("--agent", help="claude (the default) or antigravity")
    s.add_argument("--model")
    s.add_argument("--mode", help="the agent's permission mode (default: its own)")
    s.add_argument(
        "--resume", metavar="AGENT_SESSION_ID", help="continue that agent session"
    )
    s.add_argument(
        "--env", type=env_arg, action="append", default=[], metavar="NAME=VALUE"
    )
    s.add_argument(
        "--origin", help="who starts it, shown in lists (default: job: <title>)"
    )
    s.add_argument(
        "--session-meta", type=meta_arg, metavar="JSON", help="vendor options"
    )
    s.add_argument(
        "--allow-runner",
        action="store_true",
        help="let the session's own processes use the runner (start, answer, stop sessions)",
    )
    s = sub.add_parser(
        "send", help="a message: a new turn, steered into the running one, or queued"
    )
    s.add_argument("--file", help="the message, from a file")
    s.add_argument("name")
    s.add_argument("message", nargs=argparse.REMAINDER)
    s = sub.add_parser("peek", help="the session's latest output as text")
    s.add_argument("name")
    s.add_argument("lines", nargs="?", type=int, default=40)
    s = sub.add_parser(
        "answer", help="answer a permission (p1: an option id) or a question (q1: JSON)"
    )
    s.add_argument("name")
    s.add_argument("request_id")
    s.add_argument("value", nargs="?")
    choice = s.add_mutually_exclusive_group()
    choice.add_argument("--decline", action="store_true", help="decline a question")
    choice.add_argument("--cancel", action="store_true")
    s = sub.add_parser(
        "wait", help="block until the job prints a marker, waits, goes quiet or ends"
    )
    s.add_argument("name")
    s.add_argument(
        "--marker", help="a regular expression for done lines (default: <X>-DONE ...)"
    )
    s.add_argument("--timeout", type=float, default=Waiting.timeout, metavar="SECONDS")
    s.add_argument("--idle", type=float, default=Waiting.idle, metavar="SECONDS")
    s.add_argument("--every", type=float, default=Waiting.every, metavar="SECONDS")
    for verb, about in (
        ("status", "the session"),
        ("stop", "end the session (it stays on record)"),
        ("cancel", "end the running turn; the session stays up"),
        ("transcript", "the agent's own transcript file"),
    ):
        s = sub.add_parser(verb, help=about)
        s.add_argument("name")
        if verb == "status":
            s.add_argument("--json", action="store_true")
        if verb == "stop":
            s.add_argument("--reason")
    s = sub.add_parser("list", help="the sessions, oldest first")
    s.add_argument("--json", action="store_true")
    s = sub.add_parser("events", help="events as JSON lines")
    s.add_argument("name", nargs="?")
    s.add_argument("--since", type=int, default=0)
    s.add_argument("--follow", "-f", action="store_true")
    s = sub.add_parser("restart", help="restart the service as its current version")
    s.add_argument(
        "--force",
        action="store_true",
        help="even if turns run or requests wait (they're lost)",
    )
    return p


def show(s: SessionStatus) -> None:
    for key in (
        "name", "agent", "model", "state", "reason", "origin", "dir",
        "agent_session_id", "transcript", "title", "turns", "compact_window",
        "misfits", "notify_error",
    ):  # fmt: skip
        value = getattr(s, key)
        if value not in (None, "", 0) or key == "turns":
            print(f"{key}: {value}")
    if s.limit:
        print(f"limit: {s.limit.resets_at or 'unknown'} ({describe(s.limit)})")
    if s.allow_runner:
        print("allow_runner: yes")
    for event in s.pending:
        request_id, what = asked(event)
        print(f"pending {event.kind} {request_id}: {what}")
    for text in s.queued:
        print(f"queued: {text}")


class Cli:
    def __init__(self, client: Client) -> None:
        self.client = client

    def run(self, args: argparse.Namespace, environ: dict[str, str]) -> int:
        c = self.client
        match args.verb:
            case "start":
                return self.start(args, environ)
            case "send":
                text = read_task(args.file) if args.file else " ".join(args.message)
                if not text.strip():
                    raise JobError("send needs a message (or --file)")
                print(c.send(args.name, text).delivery)
            case "peek":
                for line in c.output(args.name, args.lines).lines:
                    print(line)
            case "stop":
                show(c.stop(args.name, args.reason))
            case "answer":
                body = answer_body(
                    args.request_id, args.value, args.decline, args.cancel
                )
                show(c.answer(args.name, args.request_id, body))
            case "wait":
                try:
                    marker = re.compile(args.marker) if args.marker else Waiting.marker
                except re.error as e:
                    raise JobError(f"--marker isn't a regular expression: {e}") from e
                how = Waiting(
                    marker=marker,
                    timeout=args.timeout,
                    idle=args.idle,
                    every=args.every,
                )
                print("\n".join(wait(c, args.name, how).lines), flush=True)
            case "status":
                s = c.status(args.name)
                if args.json:
                    print(json.dumps(s.model_dump(mode="json"), indent=2))
                else:
                    show(s)
            case "cancel":
                show(c.cancel(args.name))
            case "transcript":
                print(c.status(args.name).transcript or "")
            case "list":
                return self.list(args.json)
            case "events":
                path = (
                    f"/v1/sessions/{quote(args.name)}/events"
                    if args.name
                    else "/v1/events"
                )
                for event in c.events(
                    f"{path}?since={args.since}&follow={int(args.follow)}"
                ):
                    print(
                        json.dumps(event.model_dump(mode="json"), ensure_ascii=False),
                        flush=True,
                    )
            case "restart":
                c.restart(args.force)
                print("restarting; sessions resume on their next message")
        return 0

    def start(self, args: argparse.Namespace, environ: dict[str, str]) -> int:
        if args.task_file and args.task is not None:
            raise JobError("give the task as a file or as --task, not both")
        spec = JobSpec(
            title=args.title,
            dir=args.dir,
            task_file=args.task_file,
            task=args.task,
            agent=args.agent,
            model=args.model,
            mode=args.mode,
            resume=args.resume,
            env=tuple(args.env),
            origin=args.origin,
            session_meta=args.session_meta,
            allow_runner=args.allow_runner,
        )
        req = start_request(spec, environ)
        status = self.client.start(req)
        # Other tools parse this line: it comes only once the session has started.
        print(f"session: {req.name}", flush=True)
        show(status)
        return 0

    def list(self, as_json: bool) -> int:
        sessions = self.client.sessions().sessions
        if as_json:
            print(json.dumps([s.model_dump(mode="json") for s in sessions], indent=2))
            return 0
        for s in sessions:
            since = time.strftime("%Y-%m-%d %H:%M", time.localtime(s.created_at))
            model = f"/{s.model}" if s.model else ""
            extra = f" ({s.pending} waiting for an answer)" if s.pending else ""
            print(f"{s.name} {s.state} {s.agent}{model} since {since}{extra}")
        if not sessions:
            print("no sessions")
        return 0


def main(argv: Sequence[str], environ: dict[str, str], prog: str) -> int:
    args = parser(prog).parse_args(argv)
    socket = environ.get("AGENT_RUNNER_SOCKET")
    if not socket:
        print(
            f"{prog}: AGENT_RUNNER_SOCKET isn't set (agents/runner/default.nix sets it)",
            file=sys.stderr,
        )
        return 1
    cli = Cli(Client(socket))
    try:
        return cli.run(args, environ)
    except ClientError as e:
        print(f"{prog}: {e}", file=sys.stderr)
        if e.resets_at:
            print(f"{prog}: resets_at: {e.resets_at:.0f}", file=sys.stderr)
        return 1
    except JobError as e:
        print(f"{prog}: {e}", file=sys.stderr)
        return 1
    except BrokenPipeError:
        # The reader went away (`| head`): quiet, including Python's flush of stdout at exit.
        os.dup2(os.open(os.devnull, os.O_WRONLY), sys.stdout.fileno())
        return 0
    except KeyboardInterrupt:
        return 130
