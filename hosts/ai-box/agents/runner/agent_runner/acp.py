"""The Agent Client Protocol messages the runner uses (protocol version 1), as typed records.

agentclientprotocol.com has the full schema. Only the fields the runner reads or sends are here;
what agents send is `Open` (ACP lets them add fields), what the runner sends is exact. Session
updates (`session/update`) are passed on unchanged, so they stay JSON here (updates.py reads the
few the runner looks into).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

from .schema import JsonObject, Open, alias

PROTOCOL_VERSION = 1

# JSON-RPC error codes. ACP uses AUTH_REQUIRED for a missing or expired sign-in (both vendors: on
# session/new, or on the first prompt).
AUTH_REQUIRED = -32000
METHOD_NOT_FOUND = -32601
INVALID_PARAMS = -32602

type RpcId = int | str

# --- What the runner sends ----------------------------------------------------------------------


@dataclass(frozen=True)
class FsCapabilities:
    read_text_file: bool = field(default=False, metadata=alias("readTextFile"))
    write_text_file: bool = field(default=False, metadata=alias("writeTextFile"))


@dataclass(frozen=True)
class ElicitationCapabilities:
    # AskUserQuestion reaches the runner as a form (README.md, "Questions").
    form: JsonObject = field(default_factory=dict)


@dataclass(frozen=True)
class ClientCapabilities:
    fs: FsCapabilities = field(default_factory=FsCapabilities)
    terminal: bool = False
    elicitation: ElicitationCapabilities = field(
        default_factory=ElicitationCapabilities
    )


@dataclass(frozen=True)
class Implementation:
    name: str
    version: str


@dataclass(frozen=True)
class InitializeParams:
    client_info: Implementation = field(metadata=alias("clientInfo"))
    protocol_version: int = field(
        default=PROTOCOL_VERSION, metadata=alias("protocolVersion")
    )
    client_capabilities: ClientCapabilities = field(
        default_factory=ClientCapabilities, metadata=alias("clientCapabilities")
    )


@dataclass(frozen=True, kw_only=True)
class NewSessionParams:
    cwd: str
    mcp_servers: list[JsonObject] = field(
        default_factory=list, metadata=alias("mcpServers")
    )
    # Vendor options (README.md, "Start": session_meta).
    meta: JsonObject | None = field(
        default=None, metadata=alias("_meta", omit_none=True)
    )


@dataclass(frozen=True, kw_only=True)
class ResumeSessionParams(NewSessionParams):
    """session/resume and session/load."""

    session_id: str = field(metadata=alias("sessionId"))


@dataclass(frozen=True)
class SetModeParams:
    session_id: str = field(metadata=alias("sessionId"))
    mode_id: str = field(metadata=alias("modeId"))


@dataclass(frozen=True)
class SetModelParams:
    session_id: str = field(metadata=alias("sessionId"))
    model_id: str = field(metadata=alias("modelId"))


@dataclass(frozen=True)
class SetConfigOptionParams:
    session_id: str = field(metadata=alias("sessionId"))
    config_id: str = field(metadata=alias("configId"))
    value: str


@dataclass(frozen=True)
class TextBlock:
    text: str
    type: Literal["text"] = "text"


@dataclass(frozen=True)
class PromptParams:
    session_id: str = field(metadata=alias("sessionId"))
    prompt: list[TextBlock] = field(default_factory=list)


@dataclass(frozen=True)
class SteeringBehaviour:
    idle_behavior: str = field(default="promptRequired", metadata=alias("idleBehavior"))


@dataclass(frozen=True)
class SteeringMeta:
    steering: SteeringBehaviour = field(default_factory=SteeringBehaviour)


@dataclass(frozen=True)
class SteeringParams:
    """`_session/steering`: Claude's extension, a message into the running turn."""

    session_id: str = field(metadata=alias("sessionId"))
    prompt: list[TextBlock] = field(default_factory=list)
    meta: SteeringMeta = field(default_factory=SteeringMeta, metadata=alias("_meta"))


@dataclass(frozen=True)
class CancelParams:
    session_id: str = field(metadata=alias("sessionId"))


@dataclass(frozen=True, kw_only=True)
class PermissionOutcome(Open):
    outcome: Literal["selected", "cancelled"]
    option_id: str | None = field(
        default=None, metadata=alias("optionId", omit_none=True)
    )


@dataclass(frozen=True)
class RequestPermissionResponse:
    outcome: PermissionOutcome


@dataclass(frozen=True, kw_only=True)
class ElicitationResponse(Open):
    action: Literal["accept", "decline", "cancel"]
    content: JsonObject | None = field(default=None, metadata=alias(omit_none=True))


# --- What agents send ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Steering(Open):
    supported: bool = False


@dataclass(frozen=True)
class InitializeMeta(Open):
    steering: Steering | None = None


@dataclass(frozen=True)
class SessionCapabilities(Open):
    resume: JsonObject | None = None


@dataclass(frozen=True)
class AgentCapabilities(Open):
    load_session: bool = field(default=False, metadata=alias("loadSession"))
    session_capabilities: SessionCapabilities = field(
        default_factory=SessionCapabilities, metadata=alias("sessionCapabilities")
    )


@dataclass(frozen=True)
class InitializeResult(Open):
    agent_capabilities: AgentCapabilities = field(
        default_factory=AgentCapabilities, metadata=alias("agentCapabilities")
    )
    agent_info: JsonObject | None = field(default=None, metadata=alias("agentInfo"))
    meta: InitializeMeta | None = field(default=None, metadata=alias("_meta"))

    @property
    def steering(self) -> bool:
        return bool(self.meta and self.meta.steering and self.meta.steering.supported)

    @property
    def can_resume(self) -> bool:
        return self.agent_capabilities.session_capabilities.resume is not None


@dataclass(frozen=True)
class ConfigOption(Open):
    id: str
    category: str | None = None


@dataclass(frozen=True)
class ModelInfo(Open):
    model_id: str = field(metadata=alias("modelId"))


@dataclass(frozen=True)
class SessionModelState(Open):
    available_models: list[ModelInfo] = field(
        default_factory=list, metadata=alias("availableModels")
    )
    current_model_id: str | None = field(default=None, metadata=alias("currentModelId"))


@dataclass(frozen=True, kw_only=True)
class SessionSetup(Open):
    """What session/resume and session/load return: the session's options."""

    config_options: list[ConfigOption] | None = field(
        default=None, metadata=alias("configOptions")
    )
    models: SessionModelState | None = None


@dataclass(frozen=True, kw_only=True)
class NewSessionResult(SessionSetup):
    session_id: str = field(metadata=alias("sessionId"))


@dataclass(frozen=True)
class PromptResult(Open):
    stop_reason: str | None = field(default=None, metadata=alias("stopReason"))


@dataclass(frozen=True)
class SteeringResult(Open):
    outcome: str | None = None


@dataclass(frozen=True)
class SessionNotification(Open):
    """session/update: one update, passed on unchanged."""

    session_id: str = field(metadata=alias("sessionId"))
    update: JsonObject = field(default_factory=dict)


@dataclass(frozen=True)
class ToolCallRef(Open):
    tool_call_id: str = field(metadata=alias("toolCallId"))
    title: str | None = None


@dataclass(frozen=True)
class PermissionOption(Open):
    option_id: str = field(metadata=alias("optionId"))
    name: str
    kind: str


@dataclass(frozen=True)
class RequestPermissionParams(Open):
    session_id: str = field(metadata=alias("sessionId"))
    tool_call: ToolCallRef = field(metadata=alias("toolCall"))
    options: list[PermissionOption] = field(default_factory=list)


@dataclass(frozen=True)
class ElicitationParams(Open):
    """elicitation/create: a question for the user, as a form (Claude's AskUserQuestion)."""

    message: str | None = None
    mode: str | None = None
    requested_schema: JsonObject | None = field(
        default=None, metadata=alias("requestedSchema")
    )
    url: str | None = None


@dataclass(frozen=True)
class CancelRequestParams(Open):
    """$/cancel_request: the agent withdraws a request it made."""

    request_id: RpcId = field(metadata=alias("requestId"))
