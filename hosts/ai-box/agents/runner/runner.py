"""agent-runner: the coding agents' sessions on ai-box, over the Agent Client Protocol.

`agent-runner serve` is the service. Each session is an agent's own ACP server (claude-agent-acp,
`agy acp`) running as a subprocess of the service. The service holds the connection and serves a
local HTTP API on a unix socket. Every other verb is the CLI for that API. README.md (next to
this file) documents the API, the events and the states.

Everything vendor-specific comes from the agents file (AGENT_RUNNER_AGENTS), generated from
nix-config's vendor directories: the command, its environment, the mode a new session gets, where
the agent writes its transcript, and the file in which a folder is marked trusted. This file knows
only ACP.

Environment (default.nix sets all four):
  AGENT_RUNNER_SOCKET  the API's unix socket
  AGENT_RUNNER_STATE   the state folder: sessions/<name>/{session.json,events.jsonl,agent.log}
  AGENT_RUNNER_AGENTS  the agents file (JSON), read by the service
  AGENT_RUNNER_NOTIFY  the command that tells Alex when a session fails (message as last argument)
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import http.client
import json
import os
import re
import shutil
import signal
import socket
import sys
import tempfile
import time
import urllib.parse
from collections import deque
from collections.abc import (
    AsyncIterator,
    Awaitable,
    Callable,
    Iterable,
    Iterator,
    Sequence,
)
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path
from typing import Any, NoReturn

VERSION = "1"

# --- Configuration ------------------------------------------------------------------------------

# ACP's error code for "authentication required" (both vendors use it for a missing or expired
# sign-in, on session/new or on the first prompt).
AUTH_REQUIRED = -32000
METHOD_NOT_FOUND = -32601

# How long `start` waits for the agent's first sign of life after sending the task, so a sign-in
# the agent only checks on its first request still fails the start rather than later.
FIRST_UPDATE_SECONDS = 30.0
# ...and how long after that sign of life it waits for the turn to fail (or end).
AFTER_FIRST_UPDATE_SECONDS = 3.0
# Initialize, session/new or resume, set_mode, set_model: each may take this long.
SETUP_SECONDS = 120.0
# Stop: how long the agent gets after SIGTERM before SIGKILL.
STOP_GRACE_SECONDS = 5.0
# Live streams get a heartbeat event this often when nothing else happens.
HEARTBEAT_SECONDS = 15.0
# Events of all sessions kept in memory for /v1/events?since=.
RING_SIZE = 20000
# Lines of the agent's stderr kept for the reason a session failed.
STDERR_TAIL = 20
# An ACP message can carry a whole file; the default 64 KiB line limit is too small.
LINE_LIMIT = 64 * 1024 * 1024
# The service's exit code for a requested restart (systemd's Restart=on-failure starts it again).
RESTART_EXIT = 75
# Records of sessions that ended (stopped or failed) longer ago than this are deleted at startup.
KEEP_ENDED_SECONDS = 30 * 24 * 3600

NAME_PATTERN = re.compile(r"^[a-z0-9][a-z0-9-]{0,62}$")
ENV_NAME_PATTERN = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")

# Session states (README.md, "States").
STARTING, RUNNING, IDLE, WAITING, OFFLINE, FAILED, STOPPED = (
    "starting",
    "running",
    "idle",
    "waiting",
    "offline",
    "failed",
    "stopped",
)
ENDED = (FAILED, STOPPED)


class RunnerError(Exception):
    """An expected failure, reported to the caller with an HTTP status."""

    def __init__(self, message: str, status: int = 400) -> None:
        super().__init__(message)
        self.status = status


@dataclass(frozen=True)
class AgentSpec:
    """One agent from the agents file."""

    command: list[str]
    env: dict[str, str] = field(default_factory=dict)
    # Variables passed through from the service's own environment (the subscription token).
    pass_env: list[str] = field(default_factory=list)
    # The mode every new or resumed session is set to (session/set_mode); None keeps the agent's.
    mode: str | None = None
    # The agent's own transcript of a session; {session_id}, {cwd} and {cwd_slug} (the folder with
    # every character but letters and digits as "-") are filled in.
    transcript: str | None = None
    # Claude Code's .claude.json: the session's folder is marked trusted there before it starts.
    claude_trust_file: str | None = None


@dataclass(frozen=True)
class Config:
    agents: dict[str, AgentSpec]
    default_agent: str
    # Never passed to an agent: they'd switch it from the subscription to metered billing.
    refused_env: list[str]

    @classmethod
    def load(cls, path: Path) -> Config:
        data = json.loads(path.read_text())
        known = {f.name for f in fields(AgentSpec)}
        agents = {}
        for name, spec in data["agents"].items():
            if unknown := set(spec) - known:
                raise ValueError(f"agent {name}: unknown keys {sorted(unknown)}")
            agents[name] = AgentSpec(**spec)
        if data["default"] not in agents:
            raise ValueError(f"default agent {data['default']!r} isn't defined")
        return cls(agents, data["default"], list(data.get("refused_env", [])))


# --- Sessions on disk ---------------------------------------------------------------------------


@dataclass
class Record:
    """A session's record (session.json): what the API reports and what a resume needs."""

    name: str
    agent: str
    dir: str
    created_at: float
    state: str = STARTING
    # Why the session is in its state, for failed, offline and stopped.
    reason: str | None = None
    model: str | None = None
    mode: str | None = None
    # Who started it: free text such as "cc", "sculpt: <project>".
    origin: str | None = None
    # Extra environment for the agent, as given to `start` (kept for resumes).
    env: dict[str, str] = field(default_factory=dict)
    # `_meta` for session/new (vendor options, e.g. Claude's disallowed tools); kept for resumes.
    session_meta: dict[str, Any] | None = None
    # The agent's own session id (resume with it) and its transcript of the session.
    agent_session_id: str | None = None
    transcript: str | None = None
    title: str | None = None
    updated_at: float = 0.0
    turns: int = 0

    def public(self) -> dict[str, Any]:
        out = asdict(self)
        # Values may be secret-ish (tokens a caller passed); the API reports names only.
        out["env"] = sorted(self.env)
        return out

    @classmethod
    def from_json(cls, data: dict[str, Any]) -> Record:
        known = {f.name for f in fields(cls)}
        return cls(**{k: v for k, v in data.items() if k in known})


def write_private(path: Path, text: str) -> None:
    """Replace a file in one step, readable by its owner only."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.")
    with os.fdopen(fd, "w") as f:
        f.write(text)
    os.replace(tmp, path)


def trust_folder(conf: Path, folder: str) -> None:
    """Mark a folder trusted in Claude Code's .claude.json.

    Untrusted, the SDK route loads a project's deny rules but not its allow rules, and nothing
    would ever show the trust dialog.
    """
    data: Any = json.loads(conf.read_text()) if conf.exists() else {}
    projects = data.setdefault("projects", {})
    entry = projects.setdefault(folder, {})
    if entry.get("hasTrustDialogAccepted") is True:
        return
    entry["hasTrustDialogAccepted"] = True
    write_private(conf, json.dumps(data, indent=2, ensure_ascii=False) + "\n")


def transcript_path(template: str | None, session_id: str, cwd: str) -> str | None:
    if not template:
        return None
    return template.format(
        session_id=session_id, cwd=cwd, cwd_slug=re.sub(r"[^A-Za-z0-9]", "-", cwd)
    )


# --- Peek: a session's events as text -----------------------------------------------------------


def render(events: Iterable[dict[str, Any]]) -> list[str]:
    """The lines `peek` shows: what was asked, what the agent said, its tool calls and requests."""
    lines: list[str] = []
    text = ""  # the agent message being streamed

    def flush() -> None:
        nonlocal text
        if text.strip():
            lines.extend(text.strip("\n").splitlines())
        text = ""

    for event in events:
        kind = event.get("kind")
        if kind == "update":
            update = event.get("update") or {}
            what = update.get("sessionUpdate")
            content = update.get("content") or {}
            if what == "agent_message_chunk" and content.get("type") == "text":
                text += content.get("text", "")
                continue
            if what == "tool_call":
                flush()
                lines.append(
                    f"[tool] {update.get('title') or update.get('kind') or '?'}"
                )
            elif what == "tool_call_update" and update.get("status") == "failed":
                flush()
                lines.append(
                    f"[tool failed] {update.get('title') or update.get('toolCallId')}"
                )
            elif what == "plan":
                flush()
                for entry in update.get("entries") or []:
                    lines.append(
                        f"[plan {entry.get('status', '?')}] {entry.get('content', '')}"
                    )
            continue
        flush()
        if kind == "prompt":
            lines.append(f"> {event.get('text', '')}".replace("\n", " "))
        elif kind == "permission":
            options = ", ".join(
                o.get("optionId", "?") for o in event.get("options", [])
            )
            lines.append(
                f"[permission {event.get('request_id')}] {event.get('title')} ({options})"
            )
        elif kind == "question":
            lines.append(f"[question {event.get('request_id')}] {event.get('message')}")
            schema = event.get("schema") or {}
            for prop, spec in (schema.get("properties") or {}).items():
                choices = spec.get("enum") or [
                    o.get("const") for o in spec.get("oneOf") or spec.get("anyOf") or []
                ]
                lines.append(
                    f"  {prop}: {spec.get('title') or spec.get('description') or ''}"
                    + (
                        f" [{' | '.join(str(c) for c in choices if c is not None)}]"
                        if choices
                        else ""
                    )
                )
        elif kind == "turn_end":
            lines.append(f"[turn ended: {event.get('stop_reason')}]")
        elif kind == "error":
            lines.append(f"[error] {event.get('message')}")
        elif kind == "state" and event.get("state") in (FAILED, OFFLINE, STOPPED):
            lines.append(f"[{event.get('state')}] {event.get('reason') or ''}".rstrip())
    flush()
    return lines


# --- One agent process --------------------------------------------------------------------------


class RpcError(Exception):
    def __init__(self, code: int, message: str, data: Any = None) -> None:
        super().__init__(message)
        self.code = code
        self.data = data


class AgentExited(Exception):
    """The agent's process ended while a request to it was open."""


Handler = Callable[[str, dict[str, Any], Any], Awaitable[None]]


class Connection:
    """An agent's ACP server as a subprocess: newline-delimited JSON-RPC 2.0 over stdio."""

    def __init__(self, proc: asyncio.subprocess.Process, log: Path) -> None:
        self.proc = proc
        self.log = log
        self.next_id = 1
        self.pending: dict[int, asyncio.Future[Any]] = {}
        self.stderr: deque[str] = deque(maxlen=STDERR_TAIL)
        self.on_message: Handler | None = None
        self.closed = asyncio.get_running_loop().create_future()

    @classmethod
    async def spawn(
        cls, command: Sequence[str], cwd: str, env: dict[str, str], log: Path
    ) -> Connection:
        try:
            proc = await asyncio.create_subprocess_exec(
                *command,
                cwd=cwd,
                env=env,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                limit=LINE_LIMIT,
                start_new_session=True,
            )
        except OSError as e:
            raise RunnerError(f"can't run {command[0]}: {e}", 500) from e
        conn = cls(proc, log)
        asyncio.create_task(conn._read_stdout())
        asyncio.create_task(conn._read_stderr())
        return conn

    async def _read_stdout(self) -> None:
        assert self.proc.stdout
        try:
            while line := await self.proc.stdout.readline():
                try:
                    msg = json.loads(line)
                except ValueError:
                    self.stderr.append(f"(not JSON on stdout) {line[:200]!r}")
                    continue
                if not isinstance(msg, dict):
                    continue
                if "method" not in msg and "id" in msg:
                    future = self.pending.pop(msg["id"], None)
                    if future and not future.done():
                        if "error" in msg:
                            err = msg["error"] or {}
                            future.set_exception(
                                RpcError(
                                    err.get("code", 0),
                                    err.get("message", "?"),
                                    err.get("data"),
                                )
                            )
                        else:
                            future.set_result(msg.get("result"))
                    continue
                if self.on_message:
                    await self.on_message(
                        msg["method"], msg.get("params") or {}, msg.get("id")
                    )
        finally:
            code = await self.proc.wait()
            for future in self.pending.values():
                if not future.done():
                    future.set_exception(AgentExited(f"the agent exited (code {code})"))
            self.pending.clear()
            if not self.closed.done():
                self.closed.set_result(code)

    async def _read_stderr(self) -> None:
        assert self.proc.stderr
        with self.log.open("ab") as log:
            while line := await self.proc.stderr.readline():
                log.write(line)
                log.flush()
                self.stderr.append(line.decode(errors="replace").rstrip())

    def _write(self, msg: dict[str, Any]) -> None:
        if self.proc.stdin is None or self.proc.stdin.is_closing():
            raise AgentExited("the agent's input is closed")
        self.proc.stdin.write(json.dumps(msg).encode() + b"\n")

    async def request(
        self, method: str, params: dict[str, Any], timeout: float | None = None
    ) -> Any:
        rid = self.next_id
        self.next_id += 1
        future: asyncio.Future[Any] = asyncio.get_running_loop().create_future()
        self.pending[rid] = future
        self._write({"jsonrpc": "2.0", "id": rid, "method": method, "params": params})
        try:
            return await asyncio.wait_for(future, timeout)
        except TimeoutError as e:
            self.pending.pop(rid, None)
            raise RunnerError(
                f"the agent didn't answer {method} within {timeout:.0f} s", 504
            ) from e

    def notify(self, method: str, params: dict[str, Any]) -> None:
        self._write({"jsonrpc": "2.0", "method": method, "params": params})

    def respond(
        self, rid: Any, result: Any = None, error: dict[str, Any] | None = None
    ) -> None:
        msg: dict[str, Any] = {"jsonrpc": "2.0", "id": rid}
        if error is not None:
            msg["error"] = error
        else:
            msg["result"] = result
        with contextlib.suppress(AgentExited):
            self._write(msg)

    @property
    def running(self) -> bool:
        return not self.closed.done()

    def stderr_tail(self, lines: int = 5) -> str:
        return " | ".join(list(self.stderr)[-lines:])

    async def terminate(self) -> None:
        if not self.running:
            return
        with contextlib.suppress(ProcessLookupError):
            os.killpg(self.proc.pid, signal.SIGTERM)
        try:
            await asyncio.wait_for(asyncio.shield(self.closed), STOP_GRACE_SECONDS)
        except TimeoutError:
            with contextlib.suppress(ProcessLookupError):
                os.killpg(self.proc.pid, signal.SIGKILL)
            await self.closed


# --- A session ----------------------------------------------------------------------------------


@dataclass
class Pending:
    """A request from the agent that waits for an answer: a permission or a question."""

    kind: str  # "permission" or "question"
    rpc_id: Any
    event: dict[str, Any]


class Session:
    def __init__(self, runner: Runner, record: Record) -> None:
        self.runner = runner
        self.record = record
        self.conn: Connection | None = None
        self.caps: dict[str, Any] = {}
        self.pending: dict[str, Pending] = {}
        self.next_request = 1
        self.queue: deque[str] = deque()
        self.turn: asyncio.Task[None] | None = None
        self.open_lock = asyncio.Lock()
        self.stopping = False
        self.first_update = asyncio.Event()

    # Files
    @property
    def folder(self) -> Path:
        return self.runner.state / "sessions" / self.record.name

    def save(self) -> None:
        self.record.updated_at = time.time()
        write_private(
            self.folder / "session.json",
            json.dumps(asdict(self.record), indent=2) + "\n",
        )

    @property
    def spec(self) -> AgentSpec:
        return self.runner.config.agents[self.record.agent]

    def emit(self, kind: str, **data: Any) -> dict[str, Any]:
        return self.runner.emit(self, kind, data)

    def set_state(self, state: str, reason: str | None = None) -> None:
        if self.record.state == state and self.record.reason == reason:
            return
        self.record.state = state
        self.record.reason = reason
        self.save()
        self.emit("state", state=state, reason=reason)

    def settle_state(self) -> None:
        """running, waiting or idle, from what's open."""
        if self.record.state in ENDED or not (self.conn and self.conn.running):
            return
        if self.pending:
            self.set_state(WAITING)
        elif self.turn and not self.turn.done():
            self.set_state(RUNNING)
        else:
            self.set_state(IDLE)

    # Failing loudly
    async def fail(self, reason: str) -> None:
        self.set_state(FAILED, reason)
        self.emit("error", message=reason)
        self.runner.notify(
            self,
            f"agent-runner: session {self.record.name} ({self.record.agent}) failed: {reason}",
        )
        if self.conn:
            await self.conn.terminate()

    def explain(self, error: BaseException, doing: str) -> str:
        if isinstance(error, RpcError) and error.code == AUTH_REQUIRED:
            hint = (
                f" ({self.last_text.strip()[:300]})" if self.last_text.strip() else ""
            )
            return (
                f"the {self.record.agent} sign-in is missing or expired: {error}{hint}"
            )
        tail = self.conn.stderr_tail() if self.conn else ""
        return f"{doing}: {error}" + (f" (agent stderr: {tail})" if tail else "")

    @property
    def last_text(self) -> str:
        return self.runner.last_text.get(self.record.name, "")

    # Connecting
    def child_env(self) -> dict[str, str]:
        base = os.environ
        env = {
            k: base[k]
            for k in ("PATH", "HOME", "USER", "LANG", "TMPDIR", "TZ")
            if k in base
        }
        env.setdefault("LANG", "C.UTF-8")
        env.update(self.spec.env)
        if missing := [k for k in self.spec.pass_env if not base.get(k)]:
            # Without it the agent might find some other sign-in; no fallbacks.
            raise RunnerError(
                f"the runner has no {', '.join(missing)} for {self.record.agent}", 500
            )
        env.update({k: base[k] for k in self.spec.pass_env})
        env.update(self.record.env)
        for name in self.runner.config.refused_env:
            env.pop(name, None)
        return env

    async def open(self, resume: str | None) -> None:
        """Start the agent and create (or resume) its session; FAILED with the reason if not."""
        async with self.open_lock:
            if self.conn and self.conn.running:
                return
            self.set_state(STARTING)
            try:
                await self._open(resume)
            except (RpcError, RunnerError, AgentExited, OSError, ValueError) as e:
                await self.fail(self.explain(e, "the agent couldn't start"))
                raise RunnerError(self.record.reason or str(e), 502) from e
            self.settle_state()

    async def _open(self, resume: str | None) -> None:
        spec, rec = self.spec, self.record
        if spec.claude_trust_file:
            trust_folder(Path(spec.claude_trust_file), rec.dir)
        self.folder.mkdir(parents=True, exist_ok=True)
        self.conn = conn = await Connection.spawn(
            spec.command, rec.dir, self.child_env(), self.folder / "agent.log"
        )
        conn.on_message = self.on_message
        asyncio.create_task(self.watch(conn))
        init = await conn.request(
            "initialize",
            {
                "protocolVersion": 1,
                "clientCapabilities": {
                    "fs": {"readTextFile": False, "writeTextFile": False},
                    "terminal": False,
                    # AskUserQuestion reaches the runner as a form (README.md, "Questions").
                    "elicitation": {"form": {}},
                },
                "clientInfo": {"name": "ai-box agent-runner", "version": VERSION},
            },
            SETUP_SECONDS,
        )
        self.caps = init or {}
        agent_caps = self.caps.get("agentCapabilities") or {}
        params: dict[str, Any] = {"cwd": rec.dir, "mcpServers": []}
        if rec.session_meta:
            params["_meta"] = rec.session_meta
        if resume:
            session_caps = agent_caps.get("sessionCapabilities") or {}
            if "resume" in session_caps:
                result = await conn.request(
                    "session/resume", {"sessionId": resume, **params}, SETUP_SECONDS
                )
            elif agent_caps.get("loadSession"):
                # Load replays the whole conversation as updates; they're history, not news.
                self.runner.muted.add(rec.name)
                try:
                    result = await conn.request(
                        "session/load", {"sessionId": resume, **params}, SETUP_SECONDS
                    )
                finally:
                    self.runner.muted.discard(rec.name)
            else:
                raise RunnerError(f"{rec.agent} can't resume a session over ACP")
            session_id = resume
        else:
            result = await conn.request("session/new", params, SETUP_SECONDS)
            session_id = result["sessionId"]
        result = result or {}
        rec.agent_session_id = session_id
        rec.transcript = transcript_path(spec.transcript, session_id, rec.dir)
        if mode := rec.mode or spec.mode:
            await conn.request(
                "session/set_mode",
                {"sessionId": session_id, "modeId": mode},
                SETUP_SECONDS,
            )
        if rec.model:
            await self.set_model(result, rec.model)
        self.save()
        self.emit(
            "session",
            agent_session_id=session_id,
            transcript=rec.transcript,
            agent_info=self.caps.get("agentInfo"),
        )

    async def set_model(self, result: dict[str, Any], model: str) -> None:
        assert self.conn and self.record.agent_session_id
        sid = self.record.agent_session_id
        option = next(
            (
                o
                for o in result.get("configOptions") or []
                if o.get("category") == "model"
            ),
            None,
        )
        if option:
            await self.conn.request(
                "session/set_config_option",
                {"sessionId": sid, "configId": option["id"], "value": model},
                SETUP_SECONDS,
            )
        elif result.get("models"):
            available = [
                m.get("modelId") for m in result["models"].get("availableModels") or []
            ]
            if model not in available:
                raise RunnerError(
                    f"{self.record.agent} has no model {model!r}; it has: {', '.join(map(str, available))}"
                )
            await self.conn.request(
                "session/set_model", {"sessionId": sid, "modelId": model}, SETUP_SECONDS
            )
        else:
            raise RunnerError(f"{self.record.agent} offers no model choice over ACP")

    async def watch(self, conn: Connection) -> None:
        code = await conn.closed
        if conn is not self.conn:
            return
        self.drop_pending("the agent exited")
        if self.stopping or self.record.state in ENDED:
            return
        if self.record.state == STARTING:
            return  # open() reports it
        await self.fail(
            f"the agent exited (code {code}) "
            + (f"(agent stderr: {conn.stderr_tail()})" if conn.stderr else "")
        )

    # Messages from the agent
    async def on_message(self, method: str, params: dict[str, Any], rid: Any) -> None:
        if method == "session/update":
            update = params.get("update") or {}
            if update.get("sessionUpdate") == "session_info_update" and update.get(
                "title"
            ):
                self.record.title = update["title"]
            if self.record.name not in self.runner.muted:
                self.emit("update", update=update)
                self.first_update.set()
            return
        if method == "session/request_permission" and rid is not None:
            tool = params.get("toolCall") or {}
            self.ask(
                "permission",
                rid,
                title=tool.get("title"),
                tool_call_id=tool.get("toolCallId"),
                options=params.get("options") or [],
            )
            return
        if method == "elicitation/create" and rid is not None:
            self.ask(
                "question",
                rid,
                message=params.get("message"),
                mode=params.get("mode"),
                schema=params.get("requestedSchema"),
                url=params.get("url"),
            )
            return
        if method == "$/cancel_request":
            for request_id, pend in list(self.pending.items()):
                if pend.rpc_id == params.get("requestId"):
                    del self.pending[request_id]
                    self.emit(
                        "resolved", request_id=request_id, by="agent", answer=None
                    )
            self.settle_state()
            return
        if rid is not None:
            assert self.conn
            self.conn.respond(
                rid,
                error={
                    "code": METHOD_NOT_FOUND,
                    "message": f"agent-runner doesn't implement {method}",
                },
            )
            return
        self.emit("notification", method=method, params=params)

    def ask(self, kind: str, rid: Any, **data: Any) -> None:
        request_id = f"{kind[0]}{self.next_request}"
        self.next_request += 1
        event = self.emit(kind, request_id=request_id, **data)
        self.pending[request_id] = Pending(kind, rid, event)
        self.first_update.set()
        self.settle_state()

    def drop_pending(self, why: str) -> None:
        for request_id in list(self.pending):
            del self.pending[request_id]
            self.emit(
                "resolved", request_id=request_id, by="runner", answer=None, reason=why
            )

    # Answers
    def answer(self, request_id: str, body: dict[str, Any]) -> None:
        pend = self.pending.get(request_id)
        if pend is None:
            raise RunnerError(
                f"{self.record.name} has no open request {request_id}", 404
            )
        assert self.conn
        if pend.kind == "permission":
            if body.get("cancel"):
                outcome: dict[str, Any] = {"outcome": "cancelled"}
            else:
                option = body.get("option_id")
                ids = [o.get("optionId") for o in pend.event.get("options", [])]
                if option not in ids:
                    raise RunnerError(
                        f"option_id must be one of {', '.join(map(str, ids))}"
                    )
                outcome = {"outcome": "selected", "optionId": option}
            self.conn.respond(pend.rpc_id, {"outcome": outcome})
            answer: dict[str, Any] = outcome
        else:
            action = body.get("action")
            if action not in ("accept", "decline", "cancel"):
                raise RunnerError("action must be accept, decline or cancel")
            answer = {"action": action}
            if action == "accept":
                content = body.get("content")
                if not isinstance(content, dict):
                    raise RunnerError(
                        "accept needs content: an object of the schema's fields"
                    )
                answer["content"] = content
            self.conn.respond(pend.rpc_id, answer)
        del self.pending[request_id]
        self.emit("resolved", request_id=request_id, by="client", answer=answer)
        self.settle_state()

    # Prompts
    async def send(self, text: str) -> str:
        """Hand the agent a message: a new turn, steered into the running one, or queued."""
        if self.record.state == STOPPED:
            raise RunnerError(f"{self.record.name} is stopped", 409)
        if not (self.conn and self.conn.running):
            if not self.record.agent_session_id:
                raise RunnerError(
                    f"{self.record.name} never started, so there's nothing to resume",
                    409,
                )
            await self.open(resume=self.record.agent_session_id)
        assert self.conn and self.record.agent_session_id
        if self.turn and not self.turn.done():
            meta = (self.caps.get("_meta") or {}).get("steering") or {}
            if meta.get("supported"):
                result = await self.conn.request(
                    "_session/steering",
                    {
                        "sessionId": self.record.agent_session_id,
                        "prompt": [{"type": "text", "text": text}],
                        "_meta": {"steering": {"idleBehavior": "promptRequired"}},
                    },
                    SETUP_SECONDS,
                )
                if (result or {}).get("outcome") == "injected":
                    self.emit("prompt", text=text, delivery="steered")
                    return "steered"
            if self.turn and not self.turn.done():
                self.queue.append(text)
                self.emit("prompt", text=text, delivery="queued")
                return "queued"
        self.first_update.clear()
        self.turn = asyncio.create_task(self.run_turn(text))
        return "sent"

    async def run_turn(self, text: str) -> None:
        assert self.conn and self.record.agent_session_id
        self.emit("prompt", text=text, delivery="sent")
        self.runner.last_text[self.record.name] = ""
        self.record.turns += 1
        self.settle_state()
        try:
            result = await self.conn.request(
                "session/prompt",
                {
                    "sessionId": self.record.agent_session_id,
                    "prompt": [{"type": "text", "text": text}],
                },
            )
            self.emit("turn_end", stop_reason=(result or {}).get("stopReason"))
        except RpcError as e:
            if e.code == AUTH_REQUIRED:
                await self.fail(self.explain(e, "the turn failed"))
                return
            self.emit("error", message=f"the turn failed: {e}")
        except AgentExited:
            return  # watch() reports it
        finally:
            self.first_update.set()
            self.turn = None if self.turn is asyncio.current_task() else self.turn
        self.settle_state()
        if self.queue and self.record.state not in ENDED:
            next_text = self.queue.popleft()
            self.turn = asyncio.create_task(self.run_turn(next_text))

    async def cancel(self) -> None:
        self.queue.clear()
        for request_id, pend in list(self.pending.items()):
            if pend.kind == "permission":
                self.answer(request_id, {"cancel": True})
            else:
                self.answer(request_id, {"action": "cancel"})
        if self.conn and self.conn.running and self.record.agent_session_id:
            self.conn.notify(
                "session/cancel", {"sessionId": self.record.agent_session_id}
            )
            self.emit("cancel")

    async def stop(self, reason: str) -> None:
        self.stopping = True
        self.queue.clear()
        self.drop_pending("stopped")
        if self.conn:
            await self.conn.terminate()
        self.set_state(STOPPED, reason)

    def status(self) -> dict[str, Any]:
        out = self.record.public()
        out["pending"] = [p.event for p in self.pending.values()]
        out["queued"] = list(self.queue)
        out["last_message"] = self.last_text
        out["alive"] = bool(self.conn and self.conn.running)
        return out


# --- The service --------------------------------------------------------------------------------


class Runner:
    def __init__(
        self, config: Config, state: Path, notify_command: Sequence[str]
    ) -> None:
        self.config = config
        self.state = state
        self.notify_command = list(notify_command)
        self.sessions: dict[str, Session] = {}
        self.seq = 0
        self.ring: deque[dict[str, Any]] = deque(maxlen=RING_SIZE)
        self.subscribers: set[asyncio.Queue[dict[str, Any]]] = set()
        self.muted: set[str] = set()
        # The agent's latest message per session (status's last_message).
        self.last_text: dict[str, str] = {}
        # POST /v1/restart sets these: the service exits with RESTART_EXIT and systemd starts it
        # again, as its current version.
        self.stop_event: asyncio.Event | None = None
        self.restart_requested = False

    # Events
    def emit(self, session: Session, kind: str, data: dict[str, Any]) -> dict[str, Any]:
        self.seq += 1
        event = {
            "seq": self.seq,
            "ts": time.time(),
            "session": session.record.name,
            "kind": kind,
            **data,
        }
        if kind == "update":
            update = data.get("update") or {}
            content = update.get("content") or {}
            if (
                update.get("sessionUpdate") == "agent_message_chunk"
                and content.get("type") == "text"
            ):
                self.last_text[session.record.name] = self.last_text.get(
                    session.record.name, ""
                ) + content.get("text", "")
        line = json.dumps(event, ensure_ascii=False) + "\n"
        try:
            session.folder.mkdir(parents=True, exist_ok=True)
            with (session.folder / "events.jsonl").open("a") as f:
                f.write(line)
        except OSError as e:
            print(
                f"agent-runner: can't log an event of {session.record.name}: {e}",
                file=sys.stderr,
            )
        self.ring.append(event)
        for queue in list(self.subscribers):
            queue.put_nowait(event)
        return event

    def notify(self, session: Session, message: str) -> None:
        """Tell Alex (AGENT_RUNNER_NOTIFY); the outcome is the session's `notified` event."""
        print(message, file=sys.stderr, flush=True)
        if self.notify_command:
            asyncio.create_task(self._notify(session, message))

    async def _notify(self, session: Session, message: str) -> None:
        error = None
        try:
            proc = await asyncio.create_subprocess_exec(
                *self.notify_command,
                message,
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.PIPE,
            )
            _, err = await asyncio.wait_for(proc.communicate(), 60)
            if proc.returncode:
                error = f"exit {proc.returncode}: {err.decode(errors='replace').strip()[-500:]}"
        except (OSError, TimeoutError) as e:
            error = repr(e)
        if error:
            print(f"agent-runner: notify failed: {error}", file=sys.stderr)
        session.emit("notified", message=message, ok=error is None, error=error)

    # Startup: sessions from before this service started
    def load(self) -> None:
        root = self.state / "sessions"
        if not root.is_dir():
            return
        now = time.time()
        for path in sorted(root.glob("*/session.json")):
            try:
                record = Record.from_json(json.loads(path.read_text()))
            except (OSError, ValueError, TypeError) as e:
                print(f"agent-runner: skipped {path}: {e}", file=sys.stderr)
                continue
            if record.state in ENDED and now - record.updated_at > KEEP_ENDED_SECONDS:
                shutil.rmtree(path.parent, ignore_errors=True)
                continue
            self.sessions[record.name] = Session(self, record)
            self.seq = max(self.seq, last_seq(path.parent / "events.jsonl"))
        # Only now, with seq past every logged event: these emit.
        for session in self.sessions.values():
            record = session.record
            if record.state not in ENDED and record.state != OFFLINE:
                was = record.state
                session.set_state(
                    OFFLINE,
                    "the runner restarted"
                    + (" during a turn" if was in (RUNNING, WAITING) else "")
                    + "; a message resumes it",
                )

    def get(self, name: str) -> Session:
        session = self.sessions.get(name)
        if session is None:
            raise RunnerError(f"no session named {name}", 404)
        return session

    async def start(self, body: dict[str, Any]) -> Session:
        name = body.get("name")
        if not isinstance(name, str) or not NAME_PATTERN.match(name):
            raise RunnerError(
                "name: lowercase letters, digits and dashes, starting with a letter or digit (cc slugs titles)"
            )
        agent = body.get("agent") or self.config.default_agent
        if agent not in self.config.agents:
            raise RunnerError(
                f"agent must be one of {', '.join(sorted(self.config.agents))}"
            )
        folder = body.get("dir")
        if (
            not isinstance(folder, str)
            or not Path(folder).is_absolute()
            or not Path(folder).is_dir()
        ):
            raise RunnerError("dir: an existing folder, as an absolute path")
        env = body.get("env") or {}
        if not isinstance(env, dict) or not all(
            isinstance(k, str) and isinstance(v, str) for k, v in env.items()
        ):
            raise RunnerError("env: an object of strings")
        for key in env:
            if not ENV_NAME_PATTERN.match(key):
                raise RunnerError(f"env: {key!r} isn't a variable name")
            if key in self.config.refused_env:
                raise RunnerError(
                    f"env: {key} would switch the agent off its subscription; refused"
                )
        task = body.get("task")
        if task is not None and not isinstance(task, str):
            raise RunnerError("task: a string")
        for key in ("model", "mode", "origin", "resume"):
            if body.get(key) is not None and not isinstance(body[key], str):
                raise RunnerError(f"{key}: a string")
        meta = body.get("session_meta")
        if meta is not None and not isinstance(meta, dict):
            raise RunnerError("session_meta: an object")
        if old := self.sessions.get(name):
            if old.record.state not in ENDED:
                raise RunnerError(
                    f"a session named {name} is {old.record.state}; stop it first", 409
                )
            shutil.rmtree(old.folder, ignore_errors=True)
        record = Record(
            name=name,
            agent=agent,
            dir=str(Path(folder).resolve()),
            created_at=time.time(),
            model=body.get("model"),
            mode=body.get("mode"),
            origin=body.get("origin"),
            env=dict(env),
            session_meta=meta,
        )
        session = Session(self, record)
        self.sessions[name] = session
        session.save()
        await session.open(resume=body.get("resume"))
        if task:
            await session.send(task)
            # A sign-in the agent checks only on its first request fails here, not later. Claude
            # says so in a message just before the error, so give the error a moment after it.
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(
                    session.first_update.wait(), FIRST_UPDATE_SECONDS
                )
                if session.turn and not session.turn.done():
                    await asyncio.wait_for(
                        asyncio.shield(session.turn), AFTER_FIRST_UPDATE_SECONDS
                    )
            if session.record.state == FAILED:
                raise RunnerError(session.record.reason or "failed", 502)
        return session

    def listing(self) -> list[dict[str, Any]]:
        return [
            {
                **s.record.public(),
                "pending": len(s.pending),
                "alive": bool(s.conn and s.conn.running),
            }
            for s in sorted(self.sessions.values(), key=lambda s: s.record.created_at)
        ]

    async def shutdown(self) -> None:
        for session in self.sessions.values():
            if session.conn and session.conn.running:
                session.stopping = True
                await session.conn.terminate()
                if session.record.state not in ENDED:
                    session.set_state(
                        OFFLINE, "the runner stopped; a message resumes it"
                    )

    @contextlib.asynccontextmanager
    async def subscribe(self) -> AsyncIterator[asyncio.Queue[dict[str, Any]]]:
        queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
        self.subscribers.add(queue)
        try:
            yield queue
        finally:
            self.subscribers.discard(queue)


def last_seq(path: Path) -> int:
    """The seq of the last event in a session's log (0 if none)."""
    try:
        with path.open("rb") as f:
            f.seek(0, os.SEEK_END)
            size = f.tell()
            f.seek(max(0, size - 65536))
            tail = f.read().splitlines()
        for line in reversed(tail):
            with contextlib.suppress(ValueError, KeyError, TypeError):
                return int(json.loads(line)["seq"])
    except OSError:
        pass
    return 0


def read_events(path: Path, since: int = 0) -> Iterator[dict[str, Any]]:
    try:
        with path.open() as f:
            for line in f:
                try:
                    event = json.loads(line)
                except ValueError:
                    continue
                if event.get("seq", 0) > since:
                    yield event
    except FileNotFoundError:
        return


# --- HTTP on the unix socket --------------------------------------------------------------------


class Request:
    def __init__(
        self, method: str, path: str, query: dict[str, str], body: Any
    ) -> None:
        self.method = method
        self.path = path
        self.query = query
        self.body = body


async def read_request(reader: asyncio.StreamReader) -> Request:
    head = await reader.readuntil(b"\r\n\r\n")
    lines = head.decode("latin-1").split("\r\n")
    method, target, _ = lines[0].split(" ", 2)
    headers = {}
    for line in lines[1:]:
        if ":" in line:
            key, value = line.split(":", 1)
            headers[key.strip().lower()] = value.strip()
    length = int(headers.get("content-length") or 0)
    raw = await reader.readexactly(length) if length else b""
    try:
        body = json.loads(raw) if raw else {}
    except ValueError as e:
        raise RunnerError(f"the body isn't JSON: {e}") from e
    url = urllib.parse.urlsplit(target)
    query = dict(urllib.parse.parse_qsl(url.query))
    return Request(method, urllib.parse.unquote(url.path), query, body)


REASONS = {
    200: "OK",
    201: "Created",
    400: "Bad Request",
    404: "Not Found",
    405: "Method Not Allowed",
    409: "Conflict",
    500: "Internal Server Error",
    502: "Bad Gateway",
    504: "Gateway Timeout",
}


def respond(writer: asyncio.StreamWriter, status: int, body: Any) -> None:
    data = json.dumps(body, ensure_ascii=False).encode() + b"\n"
    writer.write(
        f"HTTP/1.1 {status} {REASONS.get(status, 'OK')}\r\nContent-Type: application/json\r\n"
        f"Content-Length: {len(data)}\r\nConnection: close\r\n\r\n".encode() + data
    )


class Api:
    def __init__(self, runner: Runner) -> None:
        self.runner = runner

    async def handle(
        self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter
    ) -> None:
        try:
            try:
                req = await read_request(reader)
            except (asyncio.IncompleteReadError, asyncio.LimitOverrunError, ValueError):
                return
            try:
                if await self.stream(req, writer):
                    return
                status, body = await self.route(req)
            except RunnerError as e:
                status, body = e.status, {"error": str(e)}
            except (
                Exception
            ) as e:  # noqa: BLE001 - one bad request mustn't take the service down
                print(f"agent-runner: {req.method} {req.path}: {e!r}", file=sys.stderr)
                status, body = 500, {"error": f"internal error: {e!r}"}
            respond(writer, status, body)
            await writer.drain()
        except (ConnectionError, BrokenPipeError):
            pass
        finally:
            writer.close()

    async def route(self, req: Request) -> tuple[int, Any]:
        parts = [p for p in req.path.split("/") if p]
        r = self.runner
        if parts[:1] != ["v1"]:
            raise RunnerError("unknown path; see agents/runner/README.md", 404)
        parts = parts[1:]
        match req.method, parts:
            case "POST", ["restart"]:
                r.restart_requested = True
                stop = r.stop_event
                assert stop
                asyncio.get_running_loop().call_later(0.2, stop.set)
                return 200, {"restarting": True}
            case "GET", ["agents"]:
                return 200, {
                    "default": r.config.default_agent,
                    "agents": sorted(r.config.agents),
                }
            case "GET", ["sessions"]:
                return 200, {"sessions": r.listing()}
            case "POST", ["sessions"]:
                return 201, (await r.start(req.body)).status()
            case "GET", ["sessions", name]:
                return 200, r.get(name).status()
            case "GET", ["sessions", name, "output"]:
                lines = int(req.query.get("lines") or 40)
                rendered = render(read_events(r.get(name).folder / "events.jsonl"))
                return 200, {"lines": rendered[-lines:] if lines else []}
            case "POST", ["sessions", name, "send"]:
                text = req.body.get("text")
                if not isinstance(text, str) or not text.strip():
                    raise RunnerError("text: the message")
                return 200, {"delivery": await r.get(name).send(text)}
            case "POST", ["sessions", name, "cancel"]:
                await r.get(name).cancel()
                return 200, r.get(name).status()
            case "POST", ["sessions", name, "stop"]:
                await r.get(name).stop(req.body.get("reason") or "stopped")
                return 200, r.get(name).status()
            case "POST", ["sessions", name, "requests", request_id]:
                r.get(name).answer(request_id, req.body)
                return 200, r.get(name).status()
        raise RunnerError(
            f"no {req.method} {req.path}; see agents/runner/README.md", 404
        )

    async def stream(self, req: Request, writer: asyncio.StreamWriter) -> bool:
        """GET .../events: newline-delimited JSON events, then live ones with follow=1."""
        parts = [p for p in req.path.split("/") if p]
        if (
            req.method != "GET"
            or parts not in (["v1", "events"],)
            and not (
                len(parts) == 4
                and parts[:2] == ["v1", "sessions"]
                and parts[3] == "events"
            )
        ):
            return False
        only = parts[2] if len(parts) == 4 else None
        session = self.runner.get(only) if only else None
        since = int(req.query.get("since") or 0)
        follow = req.query.get("follow") in ("1", "true", "yes")
        writer.write(
            b"HTTP/1.1 200 OK\r\nContent-Type: application/x-ndjson\r\nConnection: close\r\n\r\n"
        )
        async with self.runner.subscribe() as queue:
            if session:
                history = list(read_events(session.folder / "events.jsonl", since))
            else:
                history = [e for e in self.runner.ring if e["seq"] > since]
            last = since
            for event in history:
                writer.write(json.dumps(event, ensure_ascii=False).encode() + b"\n")
                last = event["seq"]
            await writer.drain()
            while follow:
                try:
                    event = await asyncio.wait_for(queue.get(), HEARTBEAT_SECONDS)
                except TimeoutError:
                    event = {
                        "kind": "heartbeat",
                        "ts": time.time(),
                        "seq": self.runner.seq,
                    }
                    writer.write(json.dumps(event).encode() + b"\n")
                    await writer.drain()
                    continue
                if event["seq"] <= last or (only and event["session"] != only):
                    continue
                writer.write(json.dumps(event, ensure_ascii=False).encode() + b"\n")
                await writer.drain()
        return True


async def serve(
    socket_path: Path,
    state: Path,
    agents_file: Path,
    notify: Sequence[str],
    stop: asyncio.Event | None = None,
) -> int:
    """Serve until SIGTERM/SIGINT (or, given one, until `stop` is set: the tests).

    Returns the exit code: RESTART_EXIT after POST /v1/restart, else 0.
    """
    runner = Runner(Config.load(agents_file), state, notify)
    runner.load()
    api = Api(runner)
    socket_path.parent.mkdir(parents=True, exist_ok=True)
    socket_path.unlink(missing_ok=True)
    server = await asyncio.start_unix_server(
        api.handle, path=str(socket_path), limit=LINE_LIMIT
    )
    os.chmod(socket_path, 0o660)
    if stop is None:
        stop = asyncio.Event()
        loop = asyncio.get_running_loop()
        for sig in (signal.SIGTERM, signal.SIGINT):
            loop.add_signal_handler(sig, stop.set)
    runner.stop_event = stop
    print(
        f"agent-runner: serving on {socket_path}, {len(runner.sessions)} sessions on record",
        file=sys.stderr,
        flush=True,
    )
    async with server:
        await stop.wait()
    await runner.shutdown()
    return RESTART_EXIT if runner.restart_requested else 0


# --- The CLI ------------------------------------------------------------------------------------


class UnixHTTPConnection(http.client.HTTPConnection):
    def __init__(self, path: str, timeout: float | None = None) -> None:
        super().__init__("agent-runner", timeout=timeout)
        self.socket_path = path

    def connect(self) -> None:
        self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.sock.settimeout(self.timeout)
        self.sock.connect(self.socket_path)


class CliError(Exception):
    pass


class Client:
    def __init__(self, socket_path: str) -> None:
        self.socket_path = socket_path

    def _open(
        self, method: str, path: str, body: Any = None, timeout: float | None = 600
    ) -> http.client.HTTPResponse:
        conn = UnixHTTPConnection(self.socket_path, timeout=timeout)
        data = json.dumps(body).encode() if body is not None else None
        headers = {"Content-Type": "application/json"} if data is not None else {}
        try:
            conn.request(method, path, body=data, headers=headers)
            return conn.getresponse()
        except (FileNotFoundError, ConnectionRefusedError) as e:
            raise CliError(
                f"the runner isn't running ({self.socket_path}: {e.strerror}); check: systemctl status agent-runner"
            ) from e

    def call(self, method: str, path: str, body: Any = None) -> Any:
        resp = self._open(method, path, body)
        data = json.loads(resp.read() or b"{}")
        if resp.status >= 300:
            raise CliError(data.get("error") or f"HTTP {resp.status}")
        return data

    def events(self, path: str) -> Iterator[dict[str, Any]]:
        resp = self._open("GET", path, timeout=None)
        if resp.status >= 300:
            raise CliError(
                json.loads(resp.read() or b"{}").get("error") or f"HTTP {resp.status}"
            )
        while line := resp.readline():
            if line.strip():
                yield json.loads(line)


def quote(name: str) -> str:
    return urllib.parse.quote(name, safe="")


def show_status(s: dict[str, Any]) -> None:
    for key in (
        "name",
        "agent",
        "model",
        "state",
        "reason",
        "origin",
        "dir",
        "agent_session_id",
        "transcript",
        "title",
        "turns",
    ):
        if s.get(key) not in (None, ""):
            print(f"{key}: {s[key]}")
    for p in s.get("pending") or []:
        print(
            f"pending {p.get('kind')} {p.get('request_id')}: {p.get('title') or p.get('message')}"
        )
    for q in s.get("queued") or []:
        print(f"queued: {q}")


def env_arg(value: str) -> tuple[str, str]:
    if "=" not in value:
        raise argparse.ArgumentTypeError(f"--env takes NAME=value, not {value!r}")
    key, val = value.split("=", 1)
    return key, val


def read_text(path: str) -> str:
    try:
        return os.fsdecode(Path(path).read_bytes()).rstrip("\n")
    except OSError as e:
        raise CliError(f"can't read {path}: {e.strerror}") from e


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="agent-runner",
        description="The coding agents' sessions (README.md next to runner.py).",
    )
    sub = p.add_subparsers(dest="command", required=True)
    sub.add_parser("serve", help="run the service")
    s = sub.add_parser("start", help="start a session")
    s.add_argument("name")
    s.add_argument("--agent", help="claude (default) or antigravity")
    s.add_argument("--dir", default=".", help="the folder it works in (default: here)")
    task = s.add_mutually_exclusive_group()
    task.add_argument("--task", help="the first message")
    task.add_argument("--task-file", help="the first message, from a file")
    s.add_argument("--model")
    s.add_argument(
        "--mode", help="the agent's permission mode (default: the agent's own)"
    )
    s.add_argument(
        "--resume",
        metavar="AGENT_SESSION_ID",
        help="continue this agent session instead of a new one",
    )
    s.add_argument(
        "--env", type=env_arg, action="append", default=[], metavar="NAME=VALUE"
    )
    s.add_argument(
        "--origin", help="who starts it, shown in lists (e.g. cc, sculpt: <project>)"
    )
    s.add_argument(
        "--session-meta", metavar="JSON", help="_meta for session/new (vendor options)"
    )
    s = sub.add_parser(
        "send",
        help="send a message (a new turn, steered into the running one, or queued)",
    )
    s.add_argument("name")
    s.add_argument("message", nargs=argparse.REMAINDER)
    s.add_argument("--file")
    sub.add_parser(
        "restart",
        help="restart the service as its current version (sessions go offline, a message resumes each)",
    )
    for verb in ("cancel", "stop", "status", "transcript"):
        s = sub.add_parser(verb)
        s.add_argument("name")
        if verb == "status":
            s.add_argument("--json", action="store_true")
    s = sub.add_parser("list")
    s.add_argument("--json", action="store_true")
    s = sub.add_parser("peek", help="the session's latest output as text")
    s.add_argument("name")
    s.add_argument("lines", nargs="?", type=int, default=40)
    s = sub.add_parser("answer-permission")
    s.add_argument("name")
    s.add_argument("request_id")
    s.add_argument("option_id", nargs="?")
    s.add_argument("--cancel", action="store_true")
    s = sub.add_parser("answer-question")
    s.add_argument("name")
    s.add_argument("request_id")
    group = s.add_mutually_exclusive_group(required=True)
    group.add_argument(
        "--json",
        metavar="CONTENT",
        help="accept with these field values (a JSON object)",
    )
    group.add_argument("--decline", action="store_true")
    group.add_argument("--cancel", action="store_true")
    s = sub.add_parser("events", help="events as JSON lines")
    s.add_argument("name", nargs="?")
    s.add_argument("--since", type=int, default=0)
    s.add_argument("--follow", "-f", action="store_true")
    return p


def run_cli(args: argparse.Namespace, client: Client) -> int:
    match args.command:
        case "start":
            body: dict[str, Any] = {
                "name": args.name,
                "agent": args.agent,
                "dir": str(Path(args.dir).resolve()),
                "model": args.model,
                "mode": args.mode,
                "resume": args.resume,
                "origin": args.origin,
                "env": dict(args.env),
            }
            if args.task_file:
                body["task"] = read_text(args.task_file)
            elif args.task:
                body["task"] = args.task
            if args.session_meta:
                try:
                    body["session_meta"] = json.loads(args.session_meta)
                except ValueError as e:
                    raise CliError(f"--session-meta isn't JSON: {e}") from e
            show_status(
                client.call(
                    "POST",
                    "/v1/sessions",
                    {k: v for k, v in body.items() if v is not None},
                )
            )
        case "send":
            text = read_text(args.file) if args.file else " ".join(args.message)
            if not text.strip():
                raise CliError("send needs a message (or --file)")
            print(
                client.call(
                    "POST", f"/v1/sessions/{quote(args.name)}/send", {"text": text}
                )["delivery"]
            )
        case "restart":
            client.call("POST", "/v1/restart", {})
            print("restarting; sessions resume on their next message")
        case "cancel" | "stop":
            show_status(
                client.call(
                    "POST", f"/v1/sessions/{quote(args.name)}/{args.command}", {}
                )
            )
        case "status":
            s = client.call("GET", f"/v1/sessions/{quote(args.name)}")
            print(json.dumps(s, indent=2)) if args.json else show_status(s)
        case "transcript":
            print(
                client.call("GET", f"/v1/sessions/{quote(args.name)}").get("transcript")
                or ""
            )
        case "list":
            sessions = client.call("GET", "/v1/sessions")["sessions"]
            if args.json:
                print(json.dumps(sessions, indent=2))
            for s in [] if args.json else sessions:
                since = time.strftime("%Y-%m-%d %H:%M", time.localtime(s["created_at"]))
                extra = (
                    f" ({s['pending']} waiting for an answer)"
                    if s.get("pending")
                    else ""
                )
                print(
                    f"{s['name']} {s['state']} {s['agent']}{'/' + s['model'] if s.get('model') else ''} since {since}{extra}"
                )
            if not sessions and not args.json:
                print("no sessions")
        case "peek":
            for line in client.call(
                "GET", f"/v1/sessions/{quote(args.name)}/output?lines={args.lines}"
            )["lines"]:
                print(line)
        case "answer-permission":
            if not args.cancel and not args.option_id:
                raise CliError(
                    "answer-permission needs an option id (see status) or --cancel"
                )
            body = {"cancel": True} if args.cancel else {"option_id": args.option_id}
            show_status(
                client.call(
                    "POST",
                    f"/v1/sessions/{quote(args.name)}/requests/{quote(args.request_id)}",
                    body,
                )
            )
        case "answer-question":
            if args.json is not None:
                try:
                    body = {"action": "accept", "content": json.loads(args.json)}
                except ValueError as e:
                    raise CliError(f"--json isn't JSON: {e}") from e
            else:
                body = {"action": "decline" if args.decline else "cancel"}
            show_status(
                client.call(
                    "POST",
                    f"/v1/sessions/{quote(args.name)}/requests/{quote(args.request_id)}",
                    body,
                )
            )
        case "events":
            path = (
                f"/v1/sessions/{quote(args.name)}/events" if args.name else "/v1/events"
            )
            for event in client.events(
                f"{path}?since={args.since}&follow={int(args.follow)}"
            ):
                print(json.dumps(event, ensure_ascii=False), flush=True)
    return 0


def require_env(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        die(f"{name} isn't set (agents/runner/default.nix sets it)")
    return value


def die(message: str) -> NoReturn:
    print(f"agent-runner: {message}", file=sys.stderr)
    sys.exit(1)


def main(argv: Sequence[str] | None = None) -> int:
    args = parser().parse_args(argv)
    if args.command == "serve":
        notify = os.environ.get("AGENT_RUNNER_NOTIFY", "")
        return asyncio.run(
            serve(
                Path(require_env("AGENT_RUNNER_SOCKET")),
                Path(require_env("AGENT_RUNNER_STATE")),
                Path(require_env("AGENT_RUNNER_AGENTS")),
                notify.split() if notify else [],
            )
        )
    try:
        return run_cli(args, Client(require_env("AGENT_RUNNER_SOCKET")))
    except CliError as e:
        die(str(e))
    except BrokenPipeError:
        return 0
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    sys.exit(main())
