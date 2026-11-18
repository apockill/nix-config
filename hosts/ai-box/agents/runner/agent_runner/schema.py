"""Typed records: dataclasses, checked strictly where JSON comes in, and turned back into JSON.

Every message and record the runner reads or writes (ACP messages, the agents file, session
records, events, the API's bodies) is a dataclass of this module's types. `decode` builds one from
parsed JSON and checks every value against the field's type; `encode` turns one back into JSON.

The types a field may have: str, int, float, bool, None, Literal[...], unions of these (`X | None`),
list[T], dict[str, T], another dataclass, JsonValue / JsonObject (any JSON, checked to be JSON),
and a class with its own `decode_json`/`encode_json` (events, whose fields depend on their kind).

A dataclass says what to do with keys it doesn't know in `EXTRA`: "forbid" (the default: the API's
requests, the agents file) or "ignore" (what agents send: ACP lets them add fields). A field's name
on the wire, and whether a None is left out there, come from `alias(...)` in its metadata.
"""

from __future__ import annotations

import dataclasses
import functools
import types
import typing
from typing import Any, ClassVar, Literal, Protocol, TypeAliasType, cast

type JsonValue = str | int | float | bool | None | list[JsonValue] | dict[
    str, JsonValue
]
type JsonObject = dict[str, JsonValue]

Extra = Literal["forbid", "ignore"]


class SchemaError(ValueError):
    """A value that doesn't fit its type; `path` says where (`options[0].optionId`)."""

    def __init__(self, path: str, problem: str) -> None:
        super().__init__(f"{path}: {problem}" if path else problem)
        self.path = path
        self.problem = problem


class Custom(Protocol):
    """A type that decodes and encodes itself (an event: its fields depend on its kind)."""

    @classmethod
    def decode_json(cls, data: object, path: str) -> Any: ...

    def encode_json(self) -> JsonValue: ...


def alias(name: str | None = None, *, omit_none: bool = False) -> dict[str, object]:
    """A field's metadata: its JSON name (default: the field's), and whether None is left out.

    `field(default=None, metadata=alias("sessionId", omit_none=True))`
    """
    return {"wire": name, "omit_none": omit_none}


def wire_name(f: dataclasses.Field[Any]) -> str:
    name = f.metadata.get("wire")
    return name if isinstance(name, str) else f.name


@functools.cache
def _hints(cls: type) -> dict[str, Any]:
    return typing.get_type_hints(cls)


def decode[T](cls: type[T], data: object, path: str = "") -> T:
    """`data` (parsed JSON) as a `cls`, every value checked; SchemaError says what doesn't fit."""
    return cast(T, _check(cls, data, path))


def _join(path: str, key: str) -> str:
    return f"{path}.{key}" if path else key


def _name(tp: Any) -> str:
    if tp is type(None):
        return "null"
    if isinstance(tp, TypeAliasType):
        return tp.__name__
    if isinstance(tp, type):
        return {"str": "a string", "int": "an integer", "float": "a number"}.get(
            tp.__name__, "true or false" if tp is bool else tp.__name__
        )
    origin = typing.get_origin(tp)
    if origin is list:
        return "a list"
    if origin is dict:
        return "an object"
    if origin is Literal:
        return "one of " + ", ".join(str(a) for a in typing.get_args(tp))
    return str(tp)


def _check(tp: Any, value: object, path: str) -> Any:
    if isinstance(tp, TypeAliasType):
        return _check(tp.__value__, value, path)
    if tp is Any or tp is object:
        return value
    origin = typing.get_origin(tp)
    if origin is typing.Union or isinstance(tp, types.UnionType):
        return _check_union(typing.get_args(tp), value, path)
    if origin is Literal:
        choices = typing.get_args(tp)
        if any(value == c and type(value) is type(c) for c in choices):
            return value
        raise SchemaError(path, f"must be {_name(tp)}")
    if origin is list:
        if not isinstance(value, list):
            raise SchemaError(path, "must be a list")
        (item,) = typing.get_args(tp)
        return [_check(item, v, f"{path}[{i}]") for i, v in enumerate(value)]
    if origin is dict:
        if not isinstance(value, dict):
            raise SchemaError(path, "must be an object")
        key_type, item = typing.get_args(tp)
        if key_type is not str:
            raise TypeError(f"{tp}: JSON keys are strings")
        return {k: _check(item, v, _join(path, k)) for k, v in value.items()}
    if tp is type(None):
        if value is not None:
            raise SchemaError(path, "must be null")
        return None
    if tp is bool:
        if not isinstance(value, bool):
            raise SchemaError(path, "must be true or false")
        return value
    if tp is int:
        if not isinstance(value, int) or isinstance(value, bool):
            raise SchemaError(path, "must be an integer")
        return value
    if tp is float:
        if not isinstance(value, int | float) or isinstance(value, bool):
            raise SchemaError(path, "must be a number")
        return float(value)
    if tp is str:
        if not isinstance(value, str):
            raise SchemaError(path, "must be a string")
        return value
    if isinstance(tp, type) and hasattr(tp, "decode_json"):
        return cast(type[Custom], tp).decode_json(value, path)
    if isinstance(tp, type) and dataclasses.is_dataclass(tp):
        return _check_dataclass(tp, value, path)
    raise TypeError(f"schema: no checker for {tp!r}")


def _check_union(options: tuple[Any, ...], value: object, path: str) -> Any:
    if value is None and type(None) in options:
        return None
    problems = []
    for option in options:
        if option is type(None):
            continue
        try:
            return _check(option, value, path)
        except SchemaError as e:
            problems.append(e)
    if len(problems) == 1:
        raise problems[0]
    deepest = max(problems, key=lambda e: len(e.path))
    if deepest.path != path:
        raise deepest  # one option got furthest: its complaint is the useful one
    raise SchemaError(path, "must be " + " or ".join(_name(o) for o in options))


def _check_dataclass(cls: type, value: object, path: str) -> Any:
    if not isinstance(value, dict):
        raise SchemaError(path, "must be an object")
    hints = _hints(cls)
    known = {wire_name(f): f for f in dataclasses.fields(cls) if f.init}
    extra: Extra = getattr(cls, "EXTRA", "forbid")
    if extra == "forbid" and (unknown := sorted(set(value) - set(known))):
        raise SchemaError(_join(path, unknown[0]), "unknown field")
    kwargs = {}
    for key, f in known.items():
        if key in value:
            kwargs[f.name] = _check(hints[f.name], value[key], _join(path, key))
        elif (
            f.default is dataclasses.MISSING
            and f.default_factory is dataclasses.MISSING
        ):
            raise SchemaError(_join(path, key), "missing")
    return cls(**kwargs)


def encode(value: object) -> JsonValue:
    """A record (or a value of the types above) as JSON."""
    if value is None or isinstance(value, str | int | float | bool):
        return value
    if hasattr(value, "encode_json"):
        return cast(Custom, value).encode_json()
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        out: JsonObject = {}
        for f in dataclasses.fields(value):
            item = getattr(value, f.name)
            if item is None and f.metadata.get("omit_none"):
                continue
            out[wire_name(f)] = encode(item)
        return out
    if isinstance(value, list | tuple):
        return [encode(v) for v in value]
    if isinstance(value, dict):
        return {str(k): encode(v) for k, v in value.items()}
    raise TypeError(f"schema: can't encode {type(value).__name__}")


def encode_object(value: object) -> JsonObject:
    """`encode` for a record, typed as the JSON object it is."""
    out = encode(value)
    if not isinstance(out, dict):
        raise TypeError(f"schema: {type(value).__name__} isn't encoded as an object")
    return out


class Open:
    """Base of the records agents send: unknown keys are theirs (ACP's extensions), not errors."""

    EXTRA: ClassVar[Extra] = "ignore"
