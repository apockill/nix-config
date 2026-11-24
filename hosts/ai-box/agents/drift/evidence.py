"""What the canary reads (canary.py): the checks' results, the secrets file, Claude's transcript
(its API requests: usage, the first request's text, betas, versions, permission modes, shell
outputs) and the runner's events. Pure functions of what they're given; test_evidence.py.
"""

from __future__ import annotations

import json
import shlex
from collections.abc import Iterable, Iterator, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

# The beta the API gets from a subscription (OAuth) sign-in, never from an API key.
OAUTH_BETA = "oauth-2025-04-20"
# A request's cache read must cover this share of the previous request's whole input.
CACHE_SHARE = 0.9
# A turn of the canary may take this long.
TURN_SECONDS = 240.0
# The repo the Claude session works in has these instructions: AGENTS.md, imported by CLAUDE.md.
REPO_SENTINEL = "Agents canary repository rule: keep every answer to one short line."
SHELL_CHECK = (
    'if [ -n "${CLAUDE_CODE_OAUTH_TOKEN:-}" ]; then echo CANARY-TOKEN-VISIBLE;'
    " else echo CANARY-TOKEN-HIDDEN; fi"
)


class CanaryError(Exception):
    """The canary itself can't go on (not an assumption that broke)."""


@dataclass(frozen=True)
class Check:
    name: str
    status: str  # ok, FAIL, skip
    detail: str = ""

    def line(self) -> str:
        return f"{self.status} {self.name}" + (
            f": {self.detail}" if self.detail else ""
        )


def ok(name: str, detail: str = "") -> Check:
    return Check(name, "ok", detail)


def fail(name: str, detail: str) -> Check:
    return Check(name, "FAIL", detail)


def skip(name: str, detail: str) -> Check:
    return Check(name, "skip", detail)


# --- The secrets file -----------------------------------------------------------------------------


def read_secrets(text: str, names: Iterable[str]) -> dict[str, str]:
    """`NAME=value` lines (values may be shell-quoted) for the names asked for."""
    wanted = set(names)
    found: dict[str, str] = {}
    for line in text.splitlines():
        key, sep, value = line.strip().partition("=")
        if sep and key in wanted:
            words = shlex.split(value) if value else [""]
            found[key] = words[0] if words else ""
    return found


# --- Claude's transcript ----------------------------------------------------------------------------


def records(path: Path) -> list[dict[str, Any]]:
    out = []
    for line in path.read_text(errors="replace").splitlines():
        if line.strip():
            value = json.loads(line)
            if isinstance(value, dict):
                out.append(value)
    return out


@dataclass(frozen=True)
class Usage:
    request_id: str
    input: int
    cache_write: int
    cache_read: int

    @property
    def total(self) -> int:
        return self.input + self.cache_write + self.cache_read


def main_requests(recs: Iterable[dict[str, Any]]) -> list[Usage]:
    """The main conversation's API requests, in order, once each (a response's blocks repeat it)."""
    seen: dict[str, Usage] = {}
    for r in recs:
        message = r.get("message")
        if (
            r.get("type") != "assistant"
            or r.get("isSidechain")
            or not isinstance(message, dict)
        ):
            continue
        request_id, usage = r.get("requestId"), message.get("usage")
        if not isinstance(request_id, str) or not isinstance(usage, dict):
            continue
        if message.get("model") == "<synthetic>" or request_id in seen:
            continue
        seen[request_id] = Usage(
            request_id,
            int(usage.get("input_tokens") or 0),
            int(usage.get("cache_creation_input_tokens") or 0),
            int(usage.get("cache_read_input_tokens") or 0),
        )
    return list(seen.values())


def cache_covers(before: Usage, after: Usage) -> bool:
    return after.cache_read >= CACHE_SHARE * before.total


def strings(value: Any) -> Iterator[str]:
    """Every string in a JSON value."""
    if isinstance(value, str):
        yield value
    elif isinstance(value, list):
        for v in value:
            yield from strings(v)
    elif isinstance(value, dict):
        for v in value.values():
            yield from strings(v)


def first_request_text(recs: Sequence[dict[str, Any]]) -> list[str]:
    """The strings of the session's first API request: its system prompt and every message."""
    shapes = {
        r.get("shapeHash"): r for r in recs if r.get("type") == "api-request-shape"
    }
    blobs = {r.get("hash"): r for r in recs if r.get("type") == "api-request-blob"}
    first = next(
        (r for r in recs if r.get("type") == "api-request" and r.get("keep") == 0), None
    )
    if first is None:
        raise CanaryError("the transcript records no API request")
    shape = shapes.get(first.get("shapeHash"))
    if shape is None:
        raise CanaryError("the transcript lacks the first request's shape")
    out = list(strings(shape.get("shape", {}).get("system")))
    for digest in first.get("tail") or []:
        blob = blobs.get(digest)
        if blob is None:
            raise CanaryError("the transcript lacks a message of the first request")
        out.extend(strings(blob.get("message")))
    return out


def occurrences(texts: Iterable[str], needle: str) -> int:
    return sum(t.count(needle) for t in texts)


def sentinel_of(instructions: str) -> str:
    """The user-level file's longest line: text no other file has."""
    lines = [line.strip() for line in instructions.splitlines()]
    best = max(lines, key=len, default="")
    if len(best) < 40:
        raise CanaryError("the shared AGENTS.md has no line long enough to count")
    return best


def permission_modes(recs: Iterable[dict[str, Any]]) -> set[str]:
    return {
        str(r["permissionMode"])
        for r in recs
        if r.get("type") == "user" and isinstance(r.get("permissionMode"), str)
    }


def betas(recs: Iterable[dict[str, Any]]) -> list[set[str]]:
    out = []
    for r in recs:
        params = r.get("params")
        if r.get("type") == "api-request" and isinstance(params, dict):
            out.append({str(b) for b in params.get("betas") or []})
    return out


def cli_versions(recs: Iterable[dict[str, Any]]) -> set[str]:
    return {
        str(r["version"])
        for r in recs
        if r.get("type") == "api-request" and "version" in r
    }


def shell_outputs(recs: Iterable[dict[str, Any]]) -> list[str]:
    """What the session's shell commands printed (Bash tool results)."""
    out = []
    for r in recs:
        result = r.get("toolUseResult")
        if r.get("type") == "user" and isinstance(result, dict):
            out.append(str(result.get("stdout") or ""))
    return out


# --- The runner's events ------------------------------------------------------------------------


def auth_kinds(events: Iterable[dict[str, Any]]) -> set[str]:
    """The adapter's `_auth/status_update` identities: `account` is the subscription."""
    kinds = set()
    for e in events:
        if e.get("kind") == "notification" and e.get("method") == "_auth/status_update":
            status = (e.get("params") or {}).get("authStatus") or {}
            kinds.add(str(status.get("kind")))
    return kinds


def agent_info(events: Iterable[dict[str, Any]]) -> dict[str, Any]:
    for e in events:
        if e.get("kind") == "session" and isinstance(e.get("agent_info"), dict):
            info: dict[str, Any] = e["agent_info"]
            return info
    return {}


def transcript_of(events: Iterable[dict[str, Any]]) -> str | None:
    for e in events:
        if e.get("kind") == "session":
            path = e.get("transcript")
            return str(path) if path else None
    return None


def question_schema(events: Iterable[dict[str, Any]]) -> dict[str, Any] | None:
    for e in events:
        if e.get("kind") == "question":
            schema = e.get("schema")
            return schema if isinstance(schema, dict) else {}
    return None
