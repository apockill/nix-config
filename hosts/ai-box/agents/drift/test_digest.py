"""Tests for digest.py: requests counted once, the alerts and their thresholds, idle sessions."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import digest

NOW = 1_800_000_000.0
TODAY = "2027-01-15T08:00:00.000Z"  # within a day of NOW
LAST_WEEK = "2027-01-08T08:00:00.000Z"


def request(
    request_id: str, write: int, read: int, when: str = TODAY
) -> dict[str, Any]:
    usage = {
        "input_tokens": 0,
        "cache_creation_input_tokens": write,
        "cache_read_input_tokens": read,
    }
    return {"type": "assistant", "requestId": request_id, "timestamp": when,
            "message": {"model": "claude-opus-5-5", "usage": usage}}  # fmt: skip


def api_error(uuid: str, kind: str, when: str = TODAY) -> dict[str, Any]:
    return {"type": "assistant", "uuid": uuid, "timestamp": when, "isApiErrorMessage": True,
            "error": kind, "message": {"model": "<synthetic>", "usage": {}}}  # fmt: skip


def tally(*records: dict[str, Any]) -> digest.Tally:
    t = digest.Tally()
    for r in records:
        t.add(r, NOW - digest.DAY)
    return t


def test_requests_count_once_and_only_from_the_last_day() -> None:
    t = tally(
        request("a", 10, 990), request("a", 10, 990), request("old", 5000, 0, LAST_WEEK)
    )
    assert t.requests == {"a": (0, 10, 990)}
    assert (t.reads, t.total_input) == (990, 1000)


def test_a_healthy_day() -> None:
    assert digest.alerts(tally(request("a", 10, 990)), []) == [
        "ok cache-hit: at least 95% of input read from cache",
        "ok big-context: at most 30% of cache reads above 400k tokens",
        "ok api-errors: no usage limit, no error loop",
        "ok idle-sessions: none idle over 24 h",
    ]


def test_cache_misses_and_big_contexts_alert() -> None:
    lines = digest.alerts(
        tally(request("a", 500_000, 0), request("b", 1000, 450_000)), []
    )
    assert lines[0].startswith("ALERT cache-hit")
    assert lines[1].startswith("ALERT big-context")


def test_a_usage_limit_alerts_once_seen_by_its_fields() -> None:
    t = tally(
        request("a", 10, 990),
        api_error("u1", "rate_limit"),
        api_error("u1", "rate_limit"),
    )
    assert t.errors == {"rate_limit": 1}
    assert digest.alerts(t, [])[2].startswith("ALERT api-errors: usage-limit")


def test_an_error_loop_alerts_whatever_its_kind() -> None:
    few = tally(
        *(api_error(f"u{n}", "invalid_request") for n in range(digest.ERROR_LOOP - 1))
    )
    assert digest.alerts(few, [])[2].startswith("ok api-errors")
    many = tally(
        *(api_error(f"u{n}", "invalid_request") for n in range(digest.ERROR_LOOP))
    )
    assert digest.alerts(many, [])[2].startswith("ALERT api-errors: 20 or more")


def test_a_day_without_requests() -> None:
    assert digest.alerts(digest.Tally(), [])[:2] == [
        "ok cache-hit: no requests",
        "ok big-context: no requests",
    ]


def test_idle_sessions_are_alive_idle_and_quiet_for_a_day() -> None:
    sessions = [
        {
            "name": "old",
            "alive": True,
            "state": "idle",
            "last_event_at": NOW - 2 * digest.DAY,
        },
        {"name": "fresh", "alive": True, "state": "idle", "last_event_at": NOW - 60},
        {"name": "gone", "alive": False, "state": "offline", "last_event_at": 0},
        {"name": "busy", "alive": True, "state": "running", "last_event_at": 0},
    ]
    assert digest.idle_sessions(sessions, NOW) == ["old"]
    assert (
        digest.alerts(digest.Tally(), ["old"])[3]
        == "ALERT idle-sessions: old idle over 24 h"
    )
    assert digest.alerts(digest.Tally(), None)[3].startswith(
        "ALERT idle-sessions: can't list"
    )


def test_the_last_days_files_are_read(tmp_path: Path) -> None:
    sub = tmp_path / "proj" / "s1" / "subagents"
    sub.mkdir(parents=True)
    (sub / "agent-1.jsonl").write_text(
        json.dumps(request("a", 10, 990)) + "\nnot json\n"
    )
    stale = tmp_path / "proj" / "old.jsonl"
    stale.write_text(json.dumps(request("b", 10, 990)) + "\n")
    os.utime(stale, (NOW - 3 * digest.DAY, NOW - 3 * digest.DAY))
    os.utime(sub / "agent-1.jsonl", (NOW, NOW))
    t = digest.tally(digest.transcripts(tmp_path, NOW - digest.DAY), NOW - digest.DAY)
    assert set(t.requests) == {"a"}


def test_details_give_the_numbers() -> None:
    t = tally(request("a", 10, 990), api_error("u1", "rate_limit"))
    assert digest.details(t)[1] == "cache-hit ratio: 99.0%; reads above 400k: 0.0%"
    assert digest.details(t)[2] == "API error messages: rate_limit 1"


def test_a_failed_notice_alerts() -> None:
    sessions: list[dict[str, Any]] = [
        {"name": "a", "notify_error": None},
        {"name": "b", "notify_error": "exit 1: discord down"},
    ]
    assert digest.unnotified(sessions) == ["b"]
    assert digest.alerts(digest.Tally(), [], ["b"])[-1] == (
        "ALERT notify: telling Alex failed for b"
    )
    assert digest.alerts(digest.Tally(), [], [])[-1] == "ok notify: no failed notices"
    # Unknown when the runner can't be asked: the idle-sessions alert says so.
    assert digest.alerts(digest.Tally(), None, None)[-1].startswith(
        "ALERT idle-sessions"
    )
