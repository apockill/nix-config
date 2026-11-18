"""Usage limits: a turn the agent refused because the account's quota is used up.

Read from the error's data, never its text: claude-agent-acp fails such a turn with
`data = {"errorKind": "rate_limit", "rateLimit": {"resetsAt": <Unix seconds>, "rateLimitType":
"five_hour", ...}}` (its result-end.js, `turnErrorData`). The session goes `limited` until the
reset, `send` refuses it with a 429 until then, and Alex hears of it once per reset.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from .config import UNKNOWN_LIMIT_NOTICE_SECONDS
from .store import Limit

RATE_LIMIT = "rate_limit"


class RateLimitInfo(BaseModel):
    """The Claude Agent SDK's SDKRateLimitInfo: only what the runner reads."""

    model_config = ConfigDict(extra="ignore")

    resets_at: float | None = Field(default=None, alias="resetsAt")
    rate_limit_type: str | None = Field(default=None, alias="rateLimitType")


class TurnErrorData(BaseModel):
    """A failed turn's error data, as claude-agent-acp gives it."""

    model_config = ConfigDict(extra="ignore")

    error_kind: str | None = Field(default=None, alias="errorKind")
    rate_limit: RateLimitInfo | None = Field(default=None, alias="rateLimit")


def turn_error(data: Any) -> TurnErrorData:
    """The error data's kind and limit; nothing, for data of another shape (it stays in the
    error event as it came)."""
    try:
        return TurnErrorData.model_validate(data if isinstance(data, dict) else {})
    except ValidationError:
        return TurnErrorData()


def limit_of(data: TurnErrorData) -> Limit | None:
    """The usage limit a failed turn hit, if that's why it failed."""
    if data.error_kind != RATE_LIMIT:
        return None
    info = data.rate_limit or RateLimitInfo()
    return Limit(resets_at=info.resets_at, kind=info.rate_limit_type)


def active(limit: Limit | None, now: float) -> bool:
    """Whether a limit still holds: until its reset, or, with none given, until a turn ends well."""
    return limit is not None and (limit.resets_at is None or now < limit.resets_at)


def until(limit: Limit) -> str:
    """When a limit resets, for people: `2026-11-18 07:00 PST`."""
    if limit.resets_at is None:
        return "an unknown time (the agent didn't say)"
    return time.strftime("%Y-%m-%d %H:%M %Z", time.localtime(limit.resets_at))


def describe(limit: Limit) -> str:
    kind = f" ({limit.kind})" if limit.kind else ""
    return f"usage limit{kind} until {until(limit)}"


@dataclass
class LimitNotices:
    """Alex hears of a limit once per reset, whichever session hits it first."""

    told: set[tuple[str, float]] = field(default_factory=set)
    # A limit without a reset time: when Alex was last told, per agent.
    told_unknown: dict[str, float] = field(default_factory=dict)

    def first(self, agent: str, limit: Limit, now: float) -> bool:
        if limit.resets_at is None:
            if now - self.told_unknown.get(agent, -UNKNOWN_LIMIT_NOTICE_SECONDS) < (
                UNKNOWN_LIMIT_NOTICE_SECONDS
            ):
                return False
            self.told_unknown[agent] = now
            return True
        key = (agent, limit.resets_at)
        if key in self.told:
            return False
        self.told.add(key)
        return True
