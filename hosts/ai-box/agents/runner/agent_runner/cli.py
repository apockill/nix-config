"""`agent`: the coding agents' sessions and jobs, from a shell (`agent --help`).

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

from . import kanban_lane
from . import wait as wait_module
from .api_types import SessionStatus
from .base import JsonObject
from .client import Client, ClientError, quote
from .jobs import JobError, JobSpec, answer_body, read_task, start_request
from .limits import describe
from .render import asked
from .wait import DEFAULT_MARKER, Waiting, wait


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


START = """\
The session is named after the title (lowercase letters, digits and dashes: "Sites: gate speed 2"
is sites-gate-speed-2), works in DIR, and gets the starter's PATH and TMPDIR. Its first message is
the task file or --task; with neither it starts idle. A name whose session isn't stopped or
failed is refused.

The call returns once the agent has shown signs of life, so a rejected sign-in or model fails the
start itself. Then it prints `session: <name>` first (tools parse that line) and the session. A
failed start prints the runner's error instead (and `resets_at: <Unix seconds>` at the usage
limit: the session stays, limited) and exits 1.

The vendor's defaults apply unless an option says otherwise; give one only for a reason you can
state (hermes/AGENTS.md).
"""

SEND = """\
sent: a new turn. steered: a turn was running and the agent took the message into it (Claude).
queued: a turn was running and the agent can't be steered (Antigravity); it goes when the turn
ends, survives a runner restart, and goes before a newer message. An offline session (or a failed
one that had started) is resumed first. A stopped session refuses it, and a limited one until the
reset.
"""

ANSWER = """\
The ids come from `agent status` (pending) or the permission and question events.
  p1 OPTION_ID     allow or reject a tool call with one of the request's options; or --cancel
  q1 '{"f": ...}'  answer a question (Claude's AskUserQuestion) with the form's fields as JSON;
                   or --decline, --cancel
"""

PEEK = """\
A plain-text rendering of the session's events: prompts as `> ...`, the agent's text, `[tool]
<title>`, `[permission p1] ...`, `[question q1] ...` with each field and its choices, `[turn ended:
<reason>]`, state changes.
"""

RESTART = """\
Every agent process ends and the sessions go offline; systemd starts the service again as its
current version (how a new runner from a switch takes effect), and each session resumes on its
next message. Refused while a turn runs or a request waits, naming the sessions; with --force their
turns are lost (Alex is told which) and their queued messages kept.
"""


def parser(prog: str) -> Parser:
    p = Parser(
        prog=prog,
        description="The coding agents' sessions on the agent runner"
        " (agents/runner/README.md). `agent <verb> --help` for each verb.",
    )
    sub = p.add_subparsers(dest="verb", required=True, parser_class=Parser)

    def verb(name: str, about: str, epilog: str | None = None) -> Parser:
        return sub.add_parser(
            name,
            help=about,
            description=about,
            epilog=epilog,
            formatter_class=argparse.RawDescriptionHelpFormatter,
        )

    verb("serve", "run the service (agent-runner.service)")
    s = verb("start", "start a job: a session named after its title", START)
    s.add_argument("title", help="the job's title; the session's name is made from it")
    s.add_argument("dir", help="the folder it works in (it must exist)")
    s.add_argument("task_file", nargs="?", help="its first message, from this file")
    s.add_argument("--task", help="its first message (instead of a task file)")
    s.add_argument("--agent", help="claude (the default) or antigravity")
    s.add_argument(
        "--model",
        help="one the agent offers: Claude's aliases (haiku, sonnet, opus) or a full model id;"
        " an Antigravity id (gemini-3.8-flash-low is the cheapest). Default: the agent's own",
    )
    s.add_argument(
        "--mode",
        help="the agent's permission mode. Claude: default, acceptEdits, plan, auto,"
        " bypassPermissions (default: auto, claude-agent-acp's own). Antigravity: auto unless"
        " this says otherwise (its own default mode changes its prompt and tools over ACP)",
    )
    s.add_argument(
        "--resume",
        metavar="AGENT_SESSION_ID",
        help="continue that agent session (an earlier session's agent_session_id)",
    )
    s.add_argument(
        "--env",
        type=env_arg,
        action="append",
        default=[],
        metavar="NAME=VALUE",
        help="extra environment for the agent; variables that would move it off its"
        " subscription (ANTHROPIC_API_KEY, GEMINI_API_KEY, ...) are refused."
        " CLAUDE_CODE_AUTO_COMPACT_WINDOW=<tokens> sets Claude's compaction window;"
        " ENABLE_CLAUDEAI_MCP_SERVERS=false leaves out the account's claude.ai connectors",
    )
    s.add_argument(
        "--origin", help="who starts it, shown in lists (default: job: <title>)"
    )
    s.add_argument(
        "--session-meta",
        type=meta_arg,
        metavar="JSON",
        help="vendor options, as session/new's _meta (kept for resumes). Claude:"
        ' {"claudeCode": {"options": {"disallowedTools": [...]}}} takes Claude Agent SDK'
        " options (disallowedTools is merged with the adapter's own)",
    )
    s.add_argument(
        "--allow-runner",
        action="store_true",
        help="let the session's own processes use the runner (start, answer, stop sessions);"
        " without it they get 403. Only for a job that must start jobs itself",
    )
    s = verb(
        "send", "a message: a new turn, steered into the running one, or queued", SEND
    )
    s.add_argument("--file", help="the message, from a file")
    s.add_argument("name")
    s.add_argument("message", nargs=argparse.REMAINDER)
    s = verb("peek", "the session's latest output as text", PEEK)
    s.add_argument("name")
    s.add_argument("lines", nargs="?", type=int, default=40)
    s = verb(
        "answer",
        "answer a permission (p1: an option id) or a question (q1: JSON)",
        ANSWER,
    )
    s.add_argument("name")
    s.add_argument("request_id")
    s.add_argument("value", nargs="?")
    choice = s.add_mutually_exclusive_group()
    choice.add_argument("--decline", action="store_true", help="decline a question")
    choice.add_argument("--cancel", action="store_true")
    s = verb(
        "wait",
        "block until the job prints a marker, waits, hits a limit, goes quiet or ends",
        wait_doc(),
    )
    s.add_argument("name")
    s.add_argument(
        "--marker",
        help=f"a regular expression for done lines (default: {DEFAULT_MARKER})",
    )
    s.add_argument(
        "--timeout",
        type=float,
        default=Waiting.timeout,
        metavar="SECONDS",
        help="default: %(default).0f (4 h)",
    )
    s.add_argument(
        "--idle",
        type=float,
        default=Waiting.idle,
        metavar="SECONDS",
        help="quiet this long with no turn running (default: %(default).0f)",
    )
    s.add_argument(
        "--every",
        type=float,
        default=Waiting.every,
        metavar="SECONDS",
        help="how often it looks (default: %(default).0f)",
    )
    for name, about in (
        ("status", "the session"),
        (
            "stop",
            "end the session (it stays on record until its name is reused, or 30 days)",
        ),
        (
            "cancel",
            "end the running turn, its open requests and queued messages; it stays up",
        ),
        (
            "transcript",
            "the agent's own transcript file: the session's complete record",
        ),
    ):
        s = verb(name, about)
        s.add_argument("name")
        if name == "status":
            s.add_argument("--json", action="store_true")
        if name == "stop":
            s.add_argument("--reason")
    s = verb(
        "kanban-lane",
        "work Hermes kanban cards assigned to coder as jobs (kanban_lane.py)",
    )
    s.add_argument("--agent", help="the agent (default: the runner's)")
    s.add_argument("--hermes", default="hermes", help="the hermes command")
    s = verb("list", "the sessions, oldest first")
    s.add_argument("--json", action="store_true")
    s = verb("events", "events as JSON lines (agent_runner/events.py)")
    s.add_argument("name", nargs="?", help="one session's (default: every session's)")
    s.add_argument("--since", type=int, default=0, metavar="SEQ")
    s.add_argument("--follow", "-f", action="store_true", help="then the live ones")
    s = verb("restart", "restart the service as its current version", RESTART)
    s.add_argument(
        "--force",
        action="store_true",
        help="even if turns run or requests wait (they're lost)",
    )
    return p


def wait_doc() -> str:
    """wait.py's docstring (what each outcome prints) as the epilog of `agent wait --help`."""
    return (wait_module.__doc__ or "").split("\n", 1)[1].strip("\n") + "\n"


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
            case "kanban-lane":
                kanban_lane.Lane(c, args.hermes, args.agent).run()
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
