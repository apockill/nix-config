"""Opening an agent's session: initialize, then a new session or a resumed one, then its mode
and model, each a typed ACP request (agent.py's `setup`)."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from acp.meta import AGENT_METHODS as M
from acp.meta import PROTOCOL_VERSION
from acp.schema import (
    AgentCapabilities,
    Implementation,
    InitializeRequest,
    InitializeResponse,
    LoadSessionRequest,
    LoadSessionResponse,
    NewSessionRequest,
    NewSessionResponse,
    ResumeSessionRequest,
    ResumeSessionResponse,
    SetSessionModeRequest,
    SetSessionModeResponse,
)

from .agent import CAPABILITIES, AgentProcess
from .base import JsonObject
from .config import VERSION, AgentSpec
from .errors import RunnerError
from .vendors import choose_model, transcript_path


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
    init: InitializeResponse
    session_id: str
    transcript: str | None


async def open_session(
    agent: AgentProcess,
    spec: AgentSpec,
    wanted: Wanted,
    mute: Callable[[bool], None],
    created: Callable[[str, str | None], None],
) -> Opened:
    """Initialize, then a new session or a resumed one, then its mode and model.

    `mute(True)` while session/load replays history as updates; `created` gets the agent's session
    id and transcript as soon as they're known, before mode and model (which may fail), so a
    session that fails there can still be resumed.
    """
    me = Implementation(name="ai-box agent-runner", version=VERSION)
    hello = InitializeRequest(
        protocol_version=PROTOCOL_VERSION,
        client_capabilities=CAPABILITIES,
        client_info=me,
    )
    init = await agent.setup(M["initialize"], hello, InitializeResponse)
    caps = init.agent_capabilities or AgentCapabilities()
    setup: NewSessionResponse | ResumeSessionResponse | LoadSessionResponse
    cwd, meta = wanted.dir, wanted.meta
    if session_id := wanted.resume or "":
        if caps.session_capabilities and caps.session_capabilities.resume is not None:
            again = ResumeSessionRequest(
                cwd=cwd, session_id=session_id, mcp_servers=[], field_meta=meta
            )
            setup = await agent.setup(M["session_resume"], again, ResumeSessionResponse)
        elif caps.load_session:
            load = LoadSessionRequest(
                cwd=cwd, session_id=session_id, mcp_servers=[], field_meta=meta
            )
            mute(True)
            try:
                setup = await agent.setup(M["session_load"], load, LoadSessionResponse)
            finally:
                mute(False)
        else:
            raise RunnerError(f"{wanted.agent} can't resume a session over ACP")
    else:
        new = NewSessionRequest(cwd=cwd, mcp_servers=[], field_meta=meta)
        setup = await agent.setup(M["session_new"], new, NewSessionResponse)
        session_id = setup.session_id
    transcript = transcript_path(spec.transcript, session_id, cwd)
    created(session_id, transcript)
    if mode := wanted.mode or spec.mode:
        set_mode = SetSessionModeRequest(session_id=session_id, mode_id=mode)
        await agent.setup(M["session_set_mode"], set_mode, SetSessionModeResponse)
    if wanted.model:
        choice = choose_model(wanted.agent, setup, session_id, wanted.model)
        await agent.setup(choice.method, choice.params, choice.result)
    return Opened(init, session_id, transcript)
