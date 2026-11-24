"""evidence.py: reading Claude's transcript, the runner's events and the secrets file.
The live part runs on the box (`agents-canary`)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import evidence
import pytest
from evidence import Usage

SHARED = "- **One hardware, one operator:** only the agent Alex has named runs code on hardware."


def assistant(request_id: str, write: int, read: int, **extra: Any) -> dict[str, Any]:
    usage = {
        "input_tokens": 2,
        "cache_creation_input_tokens": write,
        "cache_read_input_tokens": read,
    }
    return {"type": "assistant", "requestId": request_id, "isSidechain": False,
            "message": {"model": "claude-haiku-5-5", "usage": usage}, **extra}  # fmt: skip


def transcript(user_copies: int = 1, repo_copies: int = 1) -> list[dict[str, Any]]:
    reminder = "Contents of CLAUDE.md:\n" + "\n".join(
        [SHARED] * user_copies + [evidence.REPO_SENTINEL] * repo_copies
    )
    return [
        {"type": "api-request-shape", "shapeHash": "s1",
         "shape": {"system": [{"type": "text", "text": "You are Claude Code."}], "tools": []}},
        {"type": "api-request-blob", "hash": "b1",
         "message": {"role": "user", "content": [{"type": "text", "text": reminder}]}},
        {"type": "api-request-blob", "hash": "b2",
         "message": {"role": "user", "content": [{"type": "text", "text": "Run this."}]}},
        {"type": "api-request", "keep": 0, "tail": ["b1", "b2"], "shapeHash": "s1",
         "version": "2.1.326", "params": {"betas": ["claude-code-20250219", evidence.OAUTH_BETA]}},
        {"type": "user", "permissionMode": "auto", "message": {"content": "Run this."}},
        assistant("r1", 20000, 0),
        assistant("r1", 20000, 0),
        {"type": "user", "toolUseResult": {"stdout": "CANARY-TOKEN-HIDDEN", "stderr": ""}},
        {"type": "api-request", "keep": 2, "tail": ["b3"], "shapeHash": "s1",
         "version": "2.1.326", "params": {"betas": [evidence.OAUTH_BETA]}},
        assistant("r2", 300, 20000),
        assistant("sub", 9000, 0, isSidechain=True),
        {"type": "assistant", "message": {"model": "<synthetic>", "usage": {}}},
    ]  # fmt: skip


def test_requests_are_counted_once_and_in_order() -> None:
    assert evidence.main_requests(transcript()) == [
        Usage("r1", 2, 20000, 0),
        Usage("r2", 2, 300, 20000),
    ]


def test_the_cache_covers_a_prefix() -> None:
    first, second = evidence.main_requests(transcript())
    assert evidence.cache_covers(first, second)
    assert not evidence.cache_covers(first, Usage("r3", 2, 20000, 0))
    assert not evidence.cache_covers(second, Usage("r3", 2, 3000, 18000))


@pytest.mark.parametrize("user, repo", [(1, 1), (2, 1), (1, 0)])
def test_instruction_files_are_counted_in_the_first_request(
    user: int, repo: int
) -> None:
    text = evidence.first_request_text(transcript(user, repo))
    assert evidence.occurrences(text, SHARED) == user
    assert evidence.occurrences(text, evidence.REPO_SENTINEL) == repo


def test_a_missing_message_blob_is_the_canarys_failure_not_a_count() -> None:
    recs = [r for r in transcript() if r.get("hash") != "b1"]
    with pytest.raises(evidence.CanaryError, match="lacks a message"):
        evidence.first_request_text(recs)


def test_no_request_recorded() -> None:
    with pytest.raises(evidence.CanaryError, match="no API request"):
        evidence.first_request_text([{"type": "user"}])


def test_the_sentinel_is_the_longest_line() -> None:
    assert evidence.sentinel_of(f"# Agents\n\n{SHARED}\n- short\n") == SHARED
    with pytest.raises(evidence.CanaryError):
        evidence.sentinel_of("# tiny\n")


def test_mode_betas_versions_and_shell_output() -> None:
    recs = transcript()
    assert evidence.permission_modes(recs) == {"auto"}
    assert all(evidence.OAUTH_BETA in b for b in evidence.betas(recs))
    assert evidence.cli_versions(recs) == {"2.1.326"}
    assert evidence.shell_outputs(recs) == ["CANARY-TOKEN-HIDDEN"]


EVENTS: list[dict[str, Any]] = [
    {"seq": 1, "kind": "notification", "method": "_auth/status_update",
     "params": {"authStatus": {"kind": "account", "label": "Claude subscription"}}},
    {"seq": 2, "kind": "notification", "method": "auth/status_update", "params": {}},
    {"seq": 3, "kind": "session", "agent_session_id": "a", "transcript": "/t.jsonl",
     "agent_info": {"name": "@agentclientprotocol/claude-agent-acp", "version": "0.108.0"}},
    {"seq": 4, "kind": "question", "request_id": "q1", "message": "Red or blue?",
     "schema": {"type": "object", "properties": {"colour": {"enum": ["red", "blue"]}}}},
]  # fmt: skip


def test_the_runners_events() -> None:
    assert evidence.auth_kinds(EVENTS) == {"account"}
    assert evidence.agent_info(EVENTS)["version"] == "0.108.0"
    assert evidence.transcript_of(EVENTS) == "/t.jsonl"
    schema = evidence.question_schema(EVENTS)
    assert schema and "colour" in schema["properties"]
    assert evidence.question_schema(EVENTS[:3]) is None


def test_secrets_are_read_quoted_or_not_and_only_those_asked_for() -> None:
    text = "A=1\nCLAUDE_CODE_OAUTH_TOKEN='sk-ant-x y'\n# comment\nB=\nOTHER=2\n"
    found = evidence.read_secrets(text, ["CLAUDE_CODE_OAUTH_TOKEN", "B", "MISSING"])
    assert found == {"CLAUDE_CODE_OAUTH_TOKEN": "sk-ant-x y", "B": ""}


def test_lines_are_stable() -> None:
    assert evidence.ok("claude-cache").line() == "ok claude-cache"
    assert evidence.fail("x", "why").line() == "FAIL x: why"
    assert evidence.skip("agy", "not signed in").line() == "skip agy: not signed in"


def test_records_reads_a_jsonl_file(tmp_path: Path) -> None:
    path = tmp_path / "t.jsonl"
    path.write_text("\n".join(json.dumps(r) for r in transcript()) + "\n\n")
    assert len(evidence.records(path)) == len(transcript())
