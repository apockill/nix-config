"""Opening a session on a started agent: initialize, then a new session or a resumed one, then its
mode and model. Also the agent's environment."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass

from . import acp
from .config import SETUP_SECONDS, VERSION, AgentSpec
from .errors import RunnerError
from .rpc import Connection
from .schema import JsonObject
from .vendors import choose_model, transcript_path

# What an agent gets of the runner's own environment, before its agent's and session's.
BASE_ENV = ("PATH", "HOME", "USER", "LANG", "TMPDIR", "TZ")

CLIENT = acp.Implementation("ai-box agent-runner", VERSION)


def agent_env(
    agent: str,
    spec: AgentSpec,
    session_env: Mapping[str, str],
    refused: list[str],
    base: Mapping[str, str],
) -> dict[str, str]:
    """The agent process's environment; RunnerError if a variable it must get is missing."""
    env = {k: base[k] for k in BASE_ENV if k in base}
    env.setdefault("LANG", "C.UTF-8")
    env.update(spec.env)
    if missing := [k for k in spec.pass_env if not base.get(k)]:
        # Without it the agent might find some other sign-in; no fallbacks.
        raise RunnerError(f"the runner has no {', '.join(missing)} for {agent}", 500)
    env.update({k: base[k] for k in spec.pass_env})
    env.update(session_env)
    for name in refused:
        env.pop(name, None)
    return env


@dataclass(frozen=True, kw_only=True)
class Wanted:
    """The session to open."""

    agent: str
    dir: str
    resume: str | None = None
    mode: str | None = None
    model: str | None = None
    meta: JsonObject | None = None


@dataclass(frozen=True)
class Opened:
    init: acp.InitializeResult
    session_id: str
    transcript: str | None


async def handshake(
    conn: Connection,
    spec: AgentSpec,
    wanted: Wanted,
    mute: Callable[[bool], None],
    created: Callable[[str, str | None], None],
) -> Opened:
    """Open the session. `mute(True)` while session/load replays history as updates; `created`
    gets the agent's session id and transcript as soon as they're known, before mode and model
    (which may fail), so a session that fails there can still be resumed."""
    init = await conn.request(
        acp.InitializeResult,
        "initialize",
        acp.InitializeParams(CLIENT),
        SETUP_SECONDS,
    )
    setup: acp.SessionSetup
    if wanted.resume:
        params = acp.ResumeSessionParams(
            cwd=wanted.dir, meta=wanted.meta, session_id=wanted.resume
        )
        if init.can_resume:
            setup = await conn.request(
                acp.SessionSetup, "session/resume", params, SETUP_SECONDS
            )
        elif init.agent_capabilities.load_session:
            mute(True)
            try:
                setup = await conn.request(
                    acp.SessionSetup, "session/load", params, SETUP_SECONDS
                )
            finally:
                mute(False)
        else:
            raise RunnerError(f"{wanted.agent} can't resume a session over ACP")
        session_id = wanted.resume
    else:
        new = await conn.request(
            acp.NewSessionResult,
            "session/new",
            acp.NewSessionParams(cwd=wanted.dir, meta=wanted.meta),
            SETUP_SECONDS,
        )
        setup, session_id = new, new.session_id
    transcript = transcript_path(spec.transcript, session_id, wanted.dir)
    created(session_id, transcript)
    if mode := wanted.mode or spec.mode:
        await conn.call(
            "session/set_mode", acp.SetModeParams(session_id, mode), SETUP_SECONDS
        )
    if wanted.model:
        choice = choose_model(wanted.agent, setup, session_id, wanted.model)
        await conn.call(choice.method, choice.params, SETUP_SECONDS)
    return Opened(init, session_id, transcript)
