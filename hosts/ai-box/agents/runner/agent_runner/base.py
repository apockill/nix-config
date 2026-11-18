"""What every record of the runner's own is built on: pydantic models, strict at the boundaries.

The ACP messages are the SDK's models (agent-client-protocol); everything else the runner reads or
writes (the agents file, session records, events, the API's bodies) is a `Strict` model: unknown
fields are an error and no value is coerced into another type.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, JsonValue, ValidationError

__all__ = ["JsonObject", "JsonValue", "Strict", "StrictMutable", "describe"]

type JsonObject = dict[str, JsonValue]


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)


class StrictMutable(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, validate_assignment=True)


def describe(error: ValidationError) -> str:
    """A validation error as one line naming each field: `name: Field required; env.A: ...`."""
    parts = []
    for e in error.errors(include_url=False):
        where = ".".join(str(p) for p in e["loc"])
        parts.append(f"{where}: {e['msg']}" if where else e["msg"])
    return "; ".join(parts)
