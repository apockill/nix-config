"""Tests for schema.py: strict decoding into dataclasses, and encoding back to JSON."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

import pytest
from agent_runner.schema import (
    JsonObject,
    JsonValue,
    Open,
    SchemaError,
    alias,
    decode,
    encode,
    encode_object,
)


@dataclass(frozen=True)
class Inner:
    name: str
    size: int = 0


@dataclass(frozen=True, kw_only=True)
class Outer:
    title: str
    count: int
    ratio: float = 1.0
    on: bool = False
    colour: Literal["red", "blue"] = "red"
    tags: list[str] = field(default_factory=list)
    env: dict[str, str] = field(default_factory=dict)
    inner: Inner | None = None
    items: list[Inner] = field(default_factory=list)
    session_id: str | None = field(default=None, metadata=alias("sessionId"))
    meta: JsonObject | None = field(
        default=None, metadata=alias("_meta", omit_none=True)
    )
    either: int | str = 0


@dataclass(frozen=True)
class Lenient(Open):
    name: str


@dataclass(frozen=True)
class Anything:
    value: JsonValue


def test_a_full_record_decodes_and_encodes_back() -> None:
    data: JsonObject = {
        "title": "t",
        "count": 2,
        "ratio": 0.5,
        "on": True,
        "colour": "blue",
        "tags": ["a"],
        "env": {"A": "1"},
        "inner": {"name": "x", "size": 3},
        "items": [{"name": "y"}],
        "sessionId": "s1",
        "_meta": {"k": [1, None]},
        "either": "e",
    }
    record = decode(Outer, data)
    assert record == Outer(
        title="t",
        count=2,
        ratio=0.5,
        on=True,
        colour="blue",
        tags=["a"],
        env={"A": "1"},
        inner=Inner("x", 3),
        items=[Inner("y", 0)],
        session_id="s1",
        meta={"k": [1, None]},
        either="e",
    )
    items: JsonValue = [{"name": "y", "size": 0}]
    assert encode(record) == {**data, "items": items}


def test_defaults_fill_what_is_left_out() -> None:
    assert decode(Outer, {"title": "t", "count": 1}) == Outer(title="t", count=1)


@pytest.mark.parametrize(
    "data, message",
    [
        ({"count": 1}, "title: missing"),
        ({"title": "t", "count": 1, "extra": 1}, "extra: unknown field"),
        ({"title": 1, "count": 1}, "title: must be a string"),
        ({"title": "t", "count": True}, "count: must be an integer"),
        ({"title": "t", "count": 1.5}, "count: must be an integer"),
        ({"title": "t", "count": 1, "ratio": "1"}, "ratio: must be a number"),
        ({"title": "t", "count": 1, "ratio": False}, "ratio: must be a number"),
        ({"title": "t", "count": 1, "on": 1}, "on: must be true or false"),
        ({"title": "t", "count": 1, "colour": "green"}, "colour: must be one of"),
        ({"title": "t", "count": 1, "tags": "a"}, "tags: must be a list"),
        ({"title": "t", "count": 1, "tags": ["a", 2]}, "tags[1]: must be a string"),
        ({"title": "t", "count": 1, "env": []}, "env: must be an object"),
        ({"title": "t", "count": 1, "env": {"A": 1}}, "env.A: must be a string"),
        ({"title": "t", "count": 1, "inner": {"size": 1}}, "inner.name: missing"),
        ({"title": "t", "count": 1, "items": [{"name": 1}]}, "items[0].name"),
        ({"title": "t", "count": 1, "sessionId": 3}, "sessionId: must be"),
        ({"title": "t", "count": 1, "session_id": "x"}, "session_id: unknown"),
        ({"title": "t", "count": 1, "either": 1.5}, "either: must be"),
    ],
)
def test_what_does_not_fit_is_refused_with_its_path(
    data: JsonObject, message: str
) -> None:
    with pytest.raises(SchemaError, match=message.replace("[", r"\[")):
        decode(Outer, data)


def test_the_error_has_the_path_and_the_problem() -> None:
    with pytest.raises(SchemaError) as e:
        decode(
            Outer, {"title": "t", "count": 1, "items": [{"name": "a", "size": "big"}]}
        )
    assert e.value.path == "items[0].size"
    assert e.value.problem == "must be an integer"


def test_a_record_must_be_an_object() -> None:
    with pytest.raises(SchemaError, match="must be an object"):
        decode(Inner, ["name"])


def test_an_int_is_a_float() -> None:
    record = decode(Outer, {"title": "t", "count": 1, "ratio": 2})
    assert record.ratio == 2.0 and isinstance(record.ratio, float)


def test_open_records_ignore_what_they_do_not_know() -> None:
    assert decode(Lenient, {"name": "n", "_meta": {}, "new": 1}) == Lenient("n")
    with pytest.raises(SchemaError, match="name: missing"):
        decode(Lenient, {"other": 1})


def test_json_values_are_checked_to_be_json() -> None:
    nested: JsonValue = {"a": [1, 2.5, "s", True, None, {"b": []}]}
    assert decode(Anything, {"value": nested}).value == nested
    with pytest.raises(SchemaError, match="value"):
        decode(Anything, {"value": {1, 2}})
    with pytest.raises(SchemaError, match=r"value\.a"):
        decode(Anything, {"value": {"a": object()}})


def test_json_values_keep_their_type() -> None:
    value = decode(Anything, {"value": [1, True, 1.5]}).value
    assert value == [1, True, 1.5]
    assert isinstance(value, list)
    assert type(value[0]) is int and type(value[1]) is bool


def test_omit_none_leaves_the_key_out() -> None:
    out = encode_object(Outer(title="t", count=1))
    assert "_meta" not in out
    assert out["sessionId"] is None  # not omit_none: kept as null
    assert out["inner"] is None


def test_encode_handles_containers_and_refuses_the_rest() -> None:
    assert encode((Inner("a"), {"k": Inner("b", 1)})) == [
        {"name": "a", "size": 0},
        {"k": {"name": "b", "size": 1}},
    ]
    with pytest.raises(TypeError):
        encode(object())
    with pytest.raises(TypeError, match="isn't encoded as an object"):
        encode_object(3)


class Custom:
    def __init__(self, value: str) -> None:
        self.value = value

    def __eq__(self, other: object) -> bool:
        return isinstance(other, Custom) and other.value == self.value

    @classmethod
    def decode_json(cls, data: object, path: str) -> Custom:
        if not isinstance(data, str):
            raise SchemaError(path, "must be a custom string")
        return cls(data)

    def encode_json(self) -> JsonValue:
        return f"<{self.value}>"


@dataclass(frozen=True)
class HasCustom:
    thing: Custom


def test_a_type_can_decode_and_encode_itself() -> None:
    assert decode(HasCustom, {"thing": "x"}) == HasCustom(Custom("x"))
    assert encode(HasCustom(Custom("x"))) == {"thing": "<x>"}
    with pytest.raises(SchemaError, match="thing: must be a custom string"):
        decode(HasCustom, {"thing": 1})


@dataclass(frozen=True)
class A:
    a: int


@dataclass(frozen=True)
class B:
    b: Inner


@dataclass(frozen=True)
class OneOf:
    x: A | B


def test_unions_of_records_take_the_first_that_fits() -> None:
    assert decode(OneOf, {"x": {"a": 1}}).x == A(1)
    assert decode(OneOf, {"x": {"b": {"name": "n"}}}).x == B(Inner("n"))


def test_a_union_reports_the_option_that_got_furthest() -> None:
    with pytest.raises(SchemaError) as e:
        decode(OneOf, {"x": {"b": {"name": 3}}})
    assert e.value.path == "x.b.name"


def test_none_only_where_the_type_allows_it() -> None:
    with pytest.raises(SchemaError, match="title: must be a string"):
        decode(Outer, {"title": None, "count": 1})
    assert decode(Outer, {"title": "t", "count": 1, "inner": None}).inner is None
