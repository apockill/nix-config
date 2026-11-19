"""Tests for base.py: the strict pydantic base and how its errors read."""

from __future__ import annotations

import pytest
from agent_runner.base import JsonObject, Strict, StrictMutable, describe
from pydantic import ValidationError


class Thing(Strict):
    name: str
    count: int = 0
    ratio: float = 0.0
    extra: JsonObject | None = None


class Changing(StrictMutable):
    count: int = 0


def test_strict_refuses_unknown_fields_and_coercion() -> None:
    assert (
        Thing.model_validate({"name": "a", "ratio": 1}).ratio == 1.0
    )  # int is a number
    for bad, where in (
        ({"name": "a", "more": 1}, "more"),
        ({"name": 1}, "name"),
        ({"name": "a", "count": "3"}, "count"),
        ({"name": "a", "count": True}, "count"),
        ({}, "name"),
    ):
        with pytest.raises(ValidationError) as caught:
            Thing.model_validate(bad)
        assert describe(caught.value).startswith(f"{where}: ")


def test_strict_is_frozen_and_strict_mutable_checks_assignments() -> None:
    thing = Thing(name="a")
    with pytest.raises(ValidationError):
        thing.name = "b"  # type: ignore[misc]
    changing = Changing()
    changing.count = 2
    with pytest.raises(ValidationError):
        changing.count = "3"  # type: ignore[assignment]


def test_json_values_are_checked_as_json() -> None:
    assert Thing.model_validate(
        {"name": "a", "extra": {"x": [1, "y", None]}}
    ).extra == {"x": [1, "y", None]}
    with pytest.raises(ValidationError):
        Thing.model_validate({"name": "a", "extra": {"x": {1, 2}}})


def test_describe_names_every_field() -> None:
    with pytest.raises(ValidationError) as caught:
        Thing.model_validate({"count": "x"})
    assert describe(caught.value) == (
        "name: Field required; count: Input should be a valid integer"
    )
