"""cc: the agent's coding jobs, as sessions on the agent runner.

A job is an agent runner session (../../agents/runner/README.md) named after the job's title:
Claude Code by default, the Antigravity CLI with `--agent antigravity`. cc is a thin layer on the
runner's CLI (CC_RUNNER, `agent-runner`): it keeps the verbs Hermes and its skills use, and adds
nothing the runner doesn't do.

Jobs started before cc moved onto the runner run on in tmux (cc-tmux, CC_LEGACY). cc hands
`send`, `peek` and `stop` for a job only that tmux server knows to it, and `list` shows them too,
so nothing changes for them until they end.

`cc start` prints `session: <name>` first; other tools parse that line.
"""

from __future__ import annotations

import argparse
import os
import re
import string
import subprocess
import sys
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import NoReturn

USAGE = """\
cc start <title> <dir> <task-file> [--agent claude|antigravity] [--model M]
                                    start a job (Claude by default); prints its session name
cc send <session> <message>         send a message (steered into a running turn, or queued)
cc peek <session> [lines]           the job's latest output, last N lines (default 40)
cc answer <session> <request> <option-id | JSON>
                                    answer a permission request (p1: an option id) or a
                                    question (q1: the form's fields as a JSON object)
cc list                             jobs, with their state
cc stop <session>                   end a job
More (status, cancel, events, transcript): agent-runner --help
"""

PEEK_DEFAULT_LINES = 40

# Everything cc passes to the runner beyond its arguments: the caller's PATH (a job sees the tools
# its starter sees, as before) and its temp folder.
PASSED_ENV = ("PATH", "TMPDIR")


class CcError(Exception):
    """An expected failure: cc prints the message and exits 1."""


def slug(name: str) -> str:
    """The session name for a job title: lowercase ASCII letters, digits and dashes."""
    lower = name.translate(
        str.maketrans(string.ascii_uppercase, string.ascii_lowercase)
    )
    return re.sub(r"[^a-z0-9]+", "-", lower).strip("-")[:63].rstrip("-")


@dataclass
class Cc:
    runner: str
    legacy: str | None
    environ: Mapping[str, str]

    def run(
        self, *args: str, capture: bool = False
    ) -> subprocess.CompletedProcess[str]:
        try:
            return subprocess.run(
                args, capture_output=capture, text=True, errors="replace", check=False
            )
        except OSError as e:
            raise CcError(f"can't run {args[0]}: {e.strerror}") from e

    def exec(self, *args: str) -> int:
        """Run a command with cc's own stdout/stderr; its exit code."""
        return self.run(*args).returncode

    def on_runner(self, session: str) -> bool:
        return (
            self.run(self.runner, "status", session, "--json", capture=True).returncode
            == 0
        )

    def legacy_sessions(self) -> list[str]:
        """Jobs on the old tmux server (their names), if cc-tmux is installed."""
        if not self.legacy:
            return []
        done = self.run(self.legacy, "list", capture=True)
        if done.returncode != 0:
            return []
        return [
            line.split()[0]
            for line in done.stdout.splitlines()
            if line.strip() and line != "no jobs"
        ]

    def route(self, session: str, *args: str) -> int:
        """A verb for one job: on the runner if it's there, else on the old tmux server."""
        if self.on_runner(session):
            return self.exec(self.runner, *args)
        if session in self.legacy_sessions():
            assert self.legacy
            return self.exec(self.legacy, *args)
        # Neither knows it: the runner says so.
        return self.exec(self.runner, *args)

    def start(
        self,
        title: str,
        folder: str,
        task_file: str,
        agent: str | None,
        model: str | None,
    ) -> int:
        session = slug(title)
        if not session:
            raise CcError(f"the title {title!r} needs a letter or digit")
        if not Path(folder).is_dir():
            raise CcError(f"{folder} isn't a directory")
        if not Path(task_file).is_file():
            raise CcError(f"can't read the task file {task_file}")
        if session in self.legacy_sessions():
            raise CcError(f"a job named {session} is still running in tmux (cc-tmux)")
        args = [
            self.runner,
            "start",
            session,
            "--dir",
            str(Path(folder).resolve()),
            "--task-file",
            task_file,
            "--origin",
            f"cc: {title}",
        ]
        for var in PASSED_ENV:
            if value := self.environ.get(var):
                args += ["--env", f"{var}={value}"]
        if agent:
            args += ["--agent", agent]
        if model:
            args += ["--model", model]
        print(f"session: {session}", flush=True)
        return self.exec(*args)

    def answer(self, session: str, request: str, value: str) -> int:
        if request.startswith("p"):
            return self.exec(self.runner, "answer-permission", session, request, value)
        if request.startswith("q"):
            return self.exec(
                self.runner, "answer-question", session, request, "--json", value
            )
        raise CcError(f"{request} isn't a request id (p1, q1, ...; see cc peek)")

    def list_jobs(self) -> int:
        code = self.exec(self.runner, "list")
        legacy = self.legacy_sessions()
        if legacy:
            assert self.legacy
            out = self.run(self.legacy, "list", capture=True).stdout.splitlines()
            print("in tmux, from before the runner (Remote Control):")
            for line in out:
                print(f"  {line}")
        return code


class Parser(argparse.ArgumentParser):
    """argparse with cc's usage text on every mistake (exit 2)."""

    def error(self, message: str) -> NoReturn:
        sys.stderr.write(USAGE)
        self.exit(2, f"cc: {message}\n")


def parse(argv: Sequence[str]) -> argparse.Namespace:
    parser = Parser(prog="cc", usage=USAGE, add_help=False)
    sub = parser.add_subparsers(dest="command", required=True, parser_class=Parser)
    start = sub.add_parser("start", usage=USAGE, add_help=False)
    start.add_argument("title")
    start.add_argument("dir")
    start.add_argument("task_file")
    start.add_argument("--agent")
    start.add_argument("--model")
    send = sub.add_parser("send", usage=USAGE, add_help=False)
    send.add_argument("session")
    # Everything after the session is the message, dashes and all.
    send.add_argument("message", nargs=argparse.REMAINDER)
    peek = sub.add_parser("peek", usage=USAGE, add_help=False)
    peek.add_argument("session")
    peek.add_argument("lines", nargs="?", type=lines_arg, default=PEEK_DEFAULT_LINES)
    answer = sub.add_parser("answer", usage=USAGE, add_help=False)
    answer.add_argument("session")
    answer.add_argument("request")
    answer.add_argument("value")
    sub.add_parser("list", usage=USAGE, add_help=False)
    stop = sub.add_parser("stop", usage=USAGE, add_help=False)
    stop.add_argument("session")
    args = parser.parse_args(argv)
    if args.command == "send" and not args.message:
        parser.error("send needs a message")
    return args


def lines_arg(value: str) -> int:
    if not value.isdigit():
        raise argparse.ArgumentTypeError(f"lines must be a number, not {value!r}")
    return int(value)


def main(
    argv: Sequence[str] | None = None, environ: Mapping[str, str] | None = None
) -> int:
    args = parse(sys.argv[1:] if argv is None else argv)
    env = os.environ if environ is None else environ
    cc = Cc(env.get("CC_RUNNER") or "agent-runner", env.get("CC_LEGACY") or None, env)
    try:
        match args.command:
            case "start":
                return cc.start(
                    args.title, args.dir, args.task_file, args.agent, args.model
                )
            case "send":
                text = " ".join(args.message)
                return cc.route(args.session, "send", args.session, text)
            case "peek":
                return cc.route(args.session, "peek", args.session, str(args.lines))
            case "answer":
                return cc.answer(args.session, args.request, args.value)
            case "list":
                return cc.list_jobs()
            case "stop":
                return cc.route(args.session, "stop", args.session)
        raise AssertionError(args.command)
    except CcError as e:
        print(f"cc: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
