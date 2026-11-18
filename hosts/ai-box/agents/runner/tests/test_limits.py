"""limits.py: a usage limit read from the turn error's data, and telling Alex once per reset."""

from __future__ import annotations

import time

from agent_runner.limits import (
    LimitNotices,
    active,
    describe,
    limit_of,
    turn_error,
    until,
)
from agent_runner.store import Limit

# claude-agent-acp 0.108's data for a turn refused at the five-hour limit (result-end.js,
# turnErrorData; the rate limit info is the Claude Agent SDK's SDKRateLimitInfo).
ADAPTER = {
    "errorKind": "rate_limit",
    "rateLimit": {
        "status": "rejected",
        "resetsAt": 1795010400,
        "rateLimitType": "five_hour",
        "utilization": 1.0,
        "overageStatus": "rejected",
        "isUsingOverage": False,
    },
}


def test_the_adapters_limit() -> None:
    data = turn_error(ADAPTER)
    assert data.error_kind == "rate_limit"
    assert limit_of(data) == Limit(resets_at=1795010400.0, kind="five_hour")


def test_a_limit_without_its_info() -> None:
    # A turn refused before its first usage: the adapter has no rate limit info to send.
    assert limit_of(turn_error({"errorKind": "rate_limit"})) == Limit()


def test_other_errors_are_no_limit() -> None:
    for data in ({"errorKind": "server_error"}, {}, None, "rate_limit", ["rate_limit"]):
        assert limit_of(turn_error(data)) is None, data


def test_data_of_a_shape_it_cant_read_is_no_limit() -> None:
    # Rather than a guess: the error event keeps the data as it came.
    for data in (
        {"errorKind": 7},
        {"errorKind": "rate_limit", "rateLimit": {"resetsAt": "7am"}},
    ):
        assert turn_error(data) == turn_error(None)
        assert limit_of(turn_error(data)) is None


def test_active_until_the_reset() -> None:
    limit = Limit(resets_at=1000.0)
    assert active(limit, 999.9) and not active(limit, 1000.0)
    assert not active(None, 0.0)
    # Without a reset time it holds until a turn ends well (which clears it).
    assert active(Limit(), 1e12)


def test_describe() -> None:
    limit = Limit(resets_at=1795010400.0, kind="five_hour")
    shown = time.strftime("%Y-%m-%d %H:%M %Z", time.localtime(1795010400.0))
    assert describe(limit) == f"usage limit (five_hour) until {shown}"
    assert until(Limit()) == "an unknown time (the agent didn't say)"
    assert (
        describe(Limit()) == "usage limit until an unknown time (the agent didn't say)"
    )


def test_once_per_reset_per_agent() -> None:
    notices = LimitNotices()
    first = Limit(resets_at=1000.0, kind="five_hour")
    assert notices.first("claude", first, 10.0)
    assert not notices.first("claude", Limit(resets_at=1000.0), 20.0)
    assert notices.first("antigravity", first, 20.0)
    assert notices.first("claude", Limit(resets_at=2000.0), 1500.0)


def test_a_limit_without_a_reset_is_told_at_most_hourly() -> None:
    notices = LimitNotices()
    assert notices.first("claude", Limit(), 0.0)
    assert not notices.first("claude", Limit(), 3599.0)
    assert notices.first("claude", Limit(), 3600.0)
