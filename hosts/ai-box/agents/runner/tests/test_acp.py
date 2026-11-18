"""Tests for acp.py: what the runner sends agents is exact; what they send may carry more."""

from __future__ import annotations

import pytest
from agent_runner import acp
from agent_runner.schema import JsonObject, SchemaError, decode, encode


def test_initialize_params_are_as_before_the_split() -> None:
    params = acp.InitializeParams(acp.Implementation("ai-box agent-runner", "1"))
    assert encode(params) == {
        "clientInfo": {"name": "ai-box agent-runner", "version": "1"},
        "protocolVersion": 1,
        "clientCapabilities": {
            "fs": {"readTextFile": False, "writeTextFile": False},
            "terminal": False,
            "elicitation": {"form": {}},
        },
    }


def test_session_params_leave_meta_out_unless_given() -> None:
    assert encode(acp.NewSessionParams(cwd="/w")) == {"cwd": "/w", "mcpServers": []}
    meta: JsonObject = {"claudeCode": {"options": {"disallowedTools": ["WebFetch"]}}}
    assert encode(acp.NewSessionParams(cwd="/w", meta=meta)) == {
        "cwd": "/w",
        "mcpServers": [],
        "_meta": meta,
    }
    assert encode(acp.ResumeSessionParams(cwd="/w", session_id="s")) == {
        "cwd": "/w",
        "mcpServers": [],
        "sessionId": "s",
    }


def test_the_other_requests() -> None:
    assert encode(acp.SetModeParams("s", "auto")) == {
        "sessionId": "s",
        "modeId": "auto",
    }
    assert encode(acp.SetModelParams("s", "m")) == {"sessionId": "s", "modelId": "m"}
    assert encode(acp.SetConfigOptionParams("s", "model", "haiku")) == {
        "sessionId": "s",
        "configId": "model",
        "value": "haiku",
    }
    assert encode(acp.PromptParams("s", [acp.TextBlock("hi")])) == {
        "sessionId": "s",
        "prompt": [{"text": "hi", "type": "text"}],
    }
    assert encode(acp.SteeringParams("s", [acp.TextBlock("more")])) == {
        "sessionId": "s",
        "prompt": [{"text": "more", "type": "text"}],
        "_meta": {"steering": {"idleBehavior": "promptRequired"}},
    }
    assert encode(acp.CancelParams("s")) == {"sessionId": "s"}


def test_answers_to_the_agent() -> None:
    selected = acp.PermissionOutcome(outcome="selected", option_id="allow")
    assert encode(acp.RequestPermissionResponse(selected)) == {
        "outcome": {"outcome": "selected", "optionId": "allow"}
    }
    cancelled = acp.PermissionOutcome(outcome="cancelled")
    assert encode(cancelled) == {"outcome": "cancelled"}
    assert encode(acp.ElicitationResponse(action="decline")) == {"action": "decline"}
    accept = acp.ElicitationResponse(action="accept", content={"c": "red"})
    assert encode(accept) == {"action": "accept", "content": {"c": "red"}}


def test_initialize_result_with_vendor_extras() -> None:
    init = decode(
        acp.InitializeResult,
        {
            "protocolVersion": 1,
            "agentInfo": {"name": "claude-agent-acp", "version": "0.9"},
            "agentCapabilities": {
                "loadSession": True,
                "sessionCapabilities": {"resume": {}},
                "promptCapabilities": {"image": True},
            },
            "authMethods": [],
            "_meta": {"steering": {"supported": True}, "other": 1},
        },
    )
    assert init.steering and init.can_resume
    assert init.agent_capabilities.load_session
    assert init.agent_info == {"name": "claude-agent-acp", "version": "0.9"}


def test_initialize_result_defaults() -> None:
    init = decode(acp.InitializeResult, {})
    assert not init.steering and not init.can_resume
    assert not init.agent_capabilities.load_session
    assert not decode(acp.InitializeResult, {"_meta": None}).steering


def test_session_results() -> None:
    new = decode(
        acp.NewSessionResult,
        {
            "sessionId": "s1",
            "models": {"currentModelId": "a", "availableModels": [{"modelId": "a"}]},
            "modes": {"currentModeId": "default"},
        },
    )
    assert new.session_id == "s1"
    assert new.models and [m.model_id for m in new.models.available_models] == ["a"]
    with pytest.raises(SchemaError, match="sessionId: missing"):
        decode(acp.NewSessionResult, {})
    setup = decode(
        acp.SessionSetup, {"configOptions": [{"id": "model", "category": "model"}]}
    )
    assert setup.config_options and setup.config_options[0].id == "model"


def test_requests_from_the_agent() -> None:
    req = decode(
        acp.RequestPermissionParams,
        {
            "sessionId": "s",
            "toolCall": {"toolCallId": "t1", "title": "touch x", "kind": "edit"},
            "options": [{"optionId": "allow", "name": "Allow", "kind": "allow_once"}],
        },
    )
    assert req.tool_call.title == "touch x"
    assert req.options[0].option_id == "allow"
    with pytest.raises(SchemaError, match=r"options\[0\]\.optionId: missing"):
        decode(
            acp.RequestPermissionParams,
            {"sessionId": "s", "toolCall": {"toolCallId": "t"}, "options": [{}]},
        )
    q = decode(
        acp.ElicitationParams,
        {"mode": "form", "message": "Pick", "requestedSchema": {"type": "object"}},
    )
    assert (q.message, q.mode, q.requested_schema) == (
        "Pick",
        "form",
        {"type": "object"},
    )
    assert decode(acp.CancelRequestParams, {"requestId": 7}).request_id == 7
    assert decode(acp.CancelRequestParams, {"requestId": "x"}).request_id == "x"
    note = decode(acp.SessionNotification, {"sessionId": "s", "update": {"a": 1}})
    assert note.update == {"a": 1}
