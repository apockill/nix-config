"""cc: the agent's Claude Code jobs as Remote Control sessions in tmux.

Alex can watch and steer each job from claude.ai/code or the Claude app. Every
job is an interactive `claude --remote-control` in its own session on the
tmux server of the cc-tmux service (socket: CC_TMUX_SOCK). `cc start` records
each job (name, dir, Claude session id, environment) in CC_JOBS/<session>.json
until `cc stop`, so `cc restore` can resume its conversation after the server
restarts (at boot). default.nix packages this and sets both variables, plus
CC_TMUX, the tmux binary; each stays overridable from the environment.

Other tools parse the `session: <s>` and `url: <url>` lines `cc start` prints.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import string
import subprocess
import sys
import tempfile
import time
import uuid
from collections.abc import Callable, Mapping, Sequence
from dataclasses import asdict, dataclass, fields
from pathlib import Path
from typing import Any, NoReturn

USAGE = """\
cc start <name> <dir> <task-file>   start a job; prints its tmux session and claude.ai URL
cc send <session> <message>         type a message into a running job
cc peek <session> [lines]           the job's screen, last N non-empty lines (default 40)
cc list                             running jobs
cc stop <session>                   end a job
cc restore                          resume recorded jobs that aren't running (run at boot)
"""

# The long-lived token can't open Remote Control sessions and would take
# precedence over the `claude auth login` credentials, so jobs never see it.
OAUTH_TOKEN_VAR = "CLAUDE_CODE_OAUTH_TOKEN"

# A job's pane size, in characters: wide enough that the Remote Control URL
# fits on one line.
PANE_WIDTH = 200
PANE_HEIGHT = 50

# A job's Remote Control URL: the id after `session_` must be there, so a URL
# still being drawn (`.../session_` alone) doesn't count.
URL_PATTERN = re.compile(r"https://claude\.ai/code/session_[A-Za-z0-9]+")

# How long `cc start` waits for the URL to appear on the job's screen.
URL_TIMEOUT_SECONDS = 30

# How often `cc start` reads the job's screen while waiting for the URL. A URL
# counts once two reads in a row show the same one, so one drawn in pieces
# isn't reported cut short.
URL_POLL_SECONDS = 0.5

# Pause between typing a message and pressing Enter, so the TUI has taken the
# text in before it's submitted.
SEND_ENTER_DELAY_SECONDS = 0.3

# Lines `cc peek` shows when none are asked for.
PEEK_DEFAULT_LINES = 40

# The cc-tmux service's placeholder session, which keeps the server up with
# no jobs; it isn't a job.
KEEP_SESSION = "_keep"

# `cc list`'s line per session: name, whether claude still runs, start time.
LIST_FORMAT = "#{session_name} #{?pane_dead,exited,running} since #{t:session_created}"


class CcError(Exception):
    """An expected failure: cc prints the message and exits 1, no traceback."""


class TmuxError(CcError):
    """A tmux command failed; the message is tmux's own."""


def tmux_arg(arg: str) -> str:
    """Escape an argument so tmux passes it on verbatim.

    tmux reads an argument ending in `;` as the end of a command (so commands
    can be chained); a trailing `\\;` is a literal `;`.
    """
    return arg[:-1] + "\\;" if arg.endswith(";") else arg


class Tmux:
    """Every tmux command cc runs, on the jobs' server; tests replace it with a fake."""

    def __init__(self, binary: str, socket: str, environ: Mapping[str, str]) -> None:
        self.binary = binary
        self.socket = socket
        # tmux copies some of the client's environment into new sessions, and
        # a client with no server to talk to starts one with its environment.
        self.env = {k: v for k, v in environ.items() if k != OAUTH_TOKEN_VAR}

    def _run(self, *args: str) -> str:
        """Run one tmux command; its stdout, or TmuxError with its stderr."""
        try:
            done = subprocess.run(
                [self.binary, "-S", self.socket, *args],
                env=self.env,
                capture_output=True,
                text=True,
                errors="replace",
            )
        except OSError as e:
            raise CcError(f"can't run tmux ({self.binary}): {e}") from e
        if done.returncode != 0:
            message = done.stderr.strip() or f"tmux {args[0]} failed"
            raise TmuxError(message)
        return done.stdout

    def server_running(self) -> bool:
        """Whether the jobs' tmux server is up."""
        try:
            self._run("list-sessions")
        except TmuxError:
            return False
        return True

    def has_session(self, session: str) -> bool:
        """Whether a session of exactly this name exists (claude running or not)."""
        try:
            self._run("has-session", "-t", f"={session}")
        except TmuxError:
            return False
        return True

    def new_session(
        self, session: str, cwd: Path, env: Sequence[str], command: Sequence[str]
    ) -> None:
        """Run `command` in a new detached session that keeps its pane after it exits."""
        env_args = [a for var in env for a in ("-e", tmux_arg(var))]
        # One tmux invocation, so the pane can't exit before the option is set.
        self._run(
            "new-session",
            "-d",
            "-s",
            session,
            "-x",
            str(PANE_WIDTH),
            "-y",
            str(PANE_HEIGHT),
            "-c",
            tmux_arg(str(cwd)),
            *env_args,
            *(tmux_arg(a) for a in command),
            ";",
            "set-option",
            "-t",
            f"={session}:",
            "remain-on-exit",
            "on",
        )

    def capture(self, session: str) -> str:
        """The session's screen, wrapped lines joined."""
        return self._run("capture-pane", "-p", "-J", "-t", f"={session}:")

    def send_keys(self, session: str, *keys: str) -> None:
        """Press these keys (tmux key names) in the session."""
        self._run("send-keys", "-t", f"={session}:", *keys)

    def send_text(self, session: str, text: str) -> None:
        """Type this text literally into the session."""
        self._run("send-keys", "-t", f"={session}:", "-l", "--", tmux_arg(text))

    def list_sessions(self, fmt: str) -> str:
        """One line per session, in tmux's -F format."""
        return self._run("list-sessions", "-F", fmt)

    def kill_session(self, session: str) -> None:
        """End the session and the claude in it."""
        self._run("kill-session", "-t", f"={session}")


@dataclass(frozen=True)
class Job:
    """A job's record in CC_JOBS: what `cc restore` needs to resume it."""

    # The title given to `cc start`, also the Remote Control session's name.
    name: str
    # The directory claude runs in; Claude keeps the transcript under it.
    dir: str
    # The Claude Code session id, so `claude --resume` continues the same transcript.
    session_id: str
    # The session's environment, as VAR=value.
    env: list[str]

    @classmethod
    def load(cls, path: Path) -> Job:
        """Read a record; CcError says what's wrong with a bad one."""
        try:
            data: Any = json.loads(path.read_text())
        except (OSError, ValueError) as e:
            raise CcError(f"can't read job record {path}: {e}") from e
        return cls.from_dict(data, path)

    @classmethod
    def from_dict(cls, data: Any, path: Path) -> Job:
        """A record from its JSON; unknown, missing or mistyped fields are a CcError."""
        if not isinstance(data, dict):
            raise CcError(f"job record {path}: not a JSON object")
        expected = {f.name for f in fields(cls)}
        if missing := sorted(expected - data.keys()):
            raise CcError(f"job record {path}: missing {', '.join(missing)}")
        if unknown := sorted(data.keys() - expected):
            raise CcError(f"job record {path}: unknown {', '.join(unknown)}")
        for key in ("name", "dir", "session_id"):
            if not isinstance(data[key], str):
                raise CcError(f"job record {path}: {key} isn't a string")
        env = data["env"]
        if not isinstance(env, list) or not all(isinstance(v, str) for v in env):
            raise CcError(f"job record {path}: env isn't a list of strings")
        return cls(data["name"], data["dir"], data["session_id"], env)

    def save(self, path: Path) -> None:
        """Write the record as JSON."""
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(asdict(self), indent=2) + "\n")
        except OSError as e:
            raise CcError(f"can't write job record {path}: {e}") from e


def slug(name: str) -> str:
    """The tmux session name for a job title: lowercase ASCII letters, digits and dashes."""
    lower = name.translate(
        str.maketrans(string.ascii_uppercase, string.ascii_lowercase)
    )
    return re.sub(r"[^a-z0-9]+", "-", lower).strip("-")


def trust_dir(config_dir: Path, cwd: Path) -> None:
    """Mark the directory trusted in Claude Code's .claude.json, so no trust dialog waits for a keypress."""
    conf = config_dir / ".claude.json"
    try:
        data: Any = json.loads(conf.read_text()) if conf.exists() else {}
        projects = data.setdefault("projects", {})
        projects.setdefault(str(cwd), {})["hasTrustDialogAccepted"] = True
    except (OSError, ValueError, AttributeError, TypeError) as e:
        raise CcError(f"can't mark {cwd} trusted in {conf}: {e}") from e
    # Replaced in one step, so a claude reading it never sees half a file.
    fd, tmp = tempfile.mkstemp(dir=config_dir, prefix=".claude.json.")
    with os.fdopen(fd, "w") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
        f.write("\n")
    os.replace(tmp, conf)


@dataclass
class Cc:
    """The subcommands, with everything they touch outside the process passed in."""

    tmux: Tmux
    # CC_JOBS: one record per job, named after its tmux session.
    jobs: Path
    # The caller's environment: HOME, and what a job inherits.
    environ: Mapping[str, str]
    # Every wait goes through this; tests pass one that returns at once.
    sleep: Callable[[float], None] = time.sleep

    @property
    def home(self) -> Path:
        return Path(self.environ.get("HOME") or Path.home())

    @property
    def claude_config_dir(self) -> Path:
        """Where Claude Code keeps .claude.json: CLAUDE_CONFIG_DIR, else HOME."""
        return Path(self.environ.get("CLAUDE_CONFIG_DIR") or self.home)

    def record(self, session: str) -> Path:
        return self.jobs / f"{session}.json"

    def require_server(self) -> None:
        if not self.tmux.server_running():
            raise CcError(
                f"the jobs' tmux server ({self.tmux.socket}) isn't running; "
                "check: systemctl status cc-tmux"
            )

    def launch(self, session: str, job: Job, claude_args: Sequence[str]) -> None:
        """Run claude in a new tmux session for this job."""
        cwd = Path(job.dir)
        if not cwd.is_dir():
            raise CcError(f"{job.dir} isn't a directory")
        trust_dir(self.claude_config_dir, cwd)
        self.tmux.new_session(session, cwd, job.env, ["claude", *claude_args])

    def start(self, name: str, dir: str, task_file: str) -> int:
        session = slug(name)
        if not session:
            raise CcError(f"the name {name!r} needs a letter or digit")
        cwd = Path(dir).resolve()
        if not cwd.is_dir():
            raise CcError(f"{dir} isn't a directory")
        try:
            # Read as the shell's $(cat) did: trailing newlines dropped.
            task = os.fsdecode(Path(task_file).read_bytes()).rstrip("\n")
        except OSError as e:
            raise CcError(f"can't read the task file: {e}") from e
        self.require_server()
        if self.tmux.has_session(session):
            raise CcError(f"a job named {session} is already running")
        # The server's environment is the service's; pass the caller's non-secret basics.
        env = [
            f"PATH={self.environ.get('PATH', os.defpath)}",
            f"HOME={self.home}",
            f"TMPDIR={self.environ.get('TMPDIR') or '/tmp'}",
            f"LANG={self.environ.get('LANG') or 'C.UTF-8'}",
        ]
        job = Job(name=name, dir=str(cwd), session_id=str(uuid.uuid4()), env=env)
        job.save(self.record(session))
        try:
            self.launch(
                session,
                job,
                ["--remote-control", name, "--session-id", job.session_id, task],
            )
        except CcError:
            # Nothing to resume: claude never started.
            self.record(session).unlink(missing_ok=True)
            raise
        print(f"session: {session}", flush=True)
        url = self.wait_for_url(session)
        if url is None:
            raise CcError(
                f"no Remote Control URL after {URL_TIMEOUT_SECONDS} s; check with: cc peek {session}"
            )
        print(f"url: {url}", flush=True)
        return 0

    def wait_for_url(self, session: str) -> str | None:
        """The job's Remote Control URL once its screen shows it whole; None on timeout."""
        seen = None
        for _ in range(int(URL_TIMEOUT_SECONDS / URL_POLL_SECONDS)):
            try:
                match = URL_PATTERN.search(self.tmux.capture(session))
            except TmuxError:
                match = None
            url = match.group(0) if match else None
            if url is not None and url == seen:
                return url
            seen = url
            self.sleep(URL_POLL_SECONDS)
        return None

    def send(self, session: str, message: Sequence[str]) -> int:
        # One line: a newline would submit early.
        text = " ".join(message).replace("\n", " ")
        self.tmux.send_keys(session, "C-u")
        self.tmux.send_text(session, text)
        self.sleep(SEND_ENTER_DELAY_SECONDS)
        self.tmux.send_keys(session, "Enter")
        return 0

    def peek(self, session: str, lines: int) -> int:
        screen = [ln for ln in self.tmux.capture(session).splitlines() if ln.strip()]
        for line in screen[-lines:] if lines else []:
            print(line)
        return 0

    def list_jobs(self) -> int:
        try:
            out = self.tmux.list_sessions(LIST_FORMAT)
        except TmuxError:
            out = ""
        jobs = [ln for ln in out.splitlines() if not ln.startswith(f"{KEEP_SESSION} ")]
        print("\n".join(jobs) if jobs else "no jobs")
        return 0

    def stop(self, session: str) -> int:
        self.record(session).unlink(missing_ok=True)
        self.tmux.kill_session(session)
        return 0

    def restore(self) -> int:
        """Relaunch every recorded job whose session is gone, resuming its conversation."""
        records = sorted(self.jobs.glob("*.json")) if self.jobs.is_dir() else []
        if not records:
            return 0
        self.require_server()
        failed = False
        for path in records:
            session = path.stem
            if self.tmux.has_session(session):
                continue
            # One bad record mustn't keep the others from coming back.
            try:
                job = Job.load(path)
                self.launch(
                    session,
                    job,
                    ["--remote-control", job.name, "--resume", job.session_id],
                )
            except CcError as e:
                print(f"cc: not restored: {session}: {e}", file=sys.stderr)
                failed = True
                continue
            print(f"restored: {session}", flush=True)
        return 1 if failed else 0


class Parser(argparse.ArgumentParser):
    """argparse with cc's usage text on every mistake (exit 2)."""

    def error(self, message: str) -> NoReturn:
        sys.stderr.write(USAGE)
        self.exit(2, f"cc: {message}\n")


def parse(argv: Sequence[str]) -> argparse.Namespace:
    parser = Parser(prog="cc", usage=USAGE, add_help=False)
    sub = parser.add_subparsers(dest="command", required=True, parser_class=Parser)
    start = sub.add_parser("start", usage=USAGE, add_help=False)
    start.add_argument("name")
    start.add_argument("dir")
    start.add_argument("task_file")
    send = sub.add_parser("send", usage=USAGE, add_help=False)
    send.add_argument("session")
    # Everything after the session is the message, dashes and all.
    send.add_argument("message", nargs=argparse.REMAINDER)
    peek = sub.add_parser("peek", usage=USAGE, add_help=False)
    peek.add_argument("session")
    peek.add_argument("lines", nargs="?", type=lines_arg, default=PEEK_DEFAULT_LINES)
    sub.add_parser("list", usage=USAGE, add_help=False)
    stop = sub.add_parser("stop", usage=USAGE, add_help=False)
    stop.add_argument("session")
    sub.add_parser("restore", usage=USAGE, add_help=False)
    args = parser.parse_args(argv)
    if args.command == "send" and not args.message:
        parser.error("send needs a message")
    return args


def lines_arg(value: str) -> int:
    if not value.isdigit():
        raise argparse.ArgumentTypeError(f"lines must be a number, not {value!r}")
    return int(value)


def from_environ(environ: Mapping[str, str]) -> tuple[Tmux, Path]:
    """The real tmux and jobs directory, from CC_TMUX, CC_TMUX_SOCK and CC_JOBS."""
    missing = [v for v in ("CC_TMUX_SOCK", "CC_JOBS") if not environ.get(v)]
    if missing:
        raise CcError(f"{' and '.join(missing)} not set (default.nix sets them)")
    tmux = Tmux(environ.get("CC_TMUX") or "tmux", environ["CC_TMUX_SOCK"], environ)
    return tmux, Path(environ["CC_JOBS"])


def main(
    argv: Sequence[str] | None = None,
    tmux: Tmux | None = None,
    sleep: Callable[[float], None] = time.sleep,
) -> int:
    """Run one cc command; returns the exit code. Tests pass a fake tmux."""
    args = parse(sys.argv[1:] if argv is None else argv)
    try:
        real_tmux, jobs = from_environ(os.environ)
        cc = Cc(tmux or real_tmux, jobs, os.environ, sleep)
        match args.command:
            case "start":
                return cc.start(args.name, args.dir, args.task_file)
            case "send":
                return cc.send(args.session, args.message)
            case "peek":
                return cc.peek(args.session, args.lines)
            case "list":
                return cc.list_jobs()
            case "stop":
                return cc.stop(args.session)
            case "restore":
                return cc.restore()
        raise AssertionError(args.command)
    except TmuxError as e:
        print(e, file=sys.stderr)
        return 1
    except CcError as e:
        print(f"cc: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
