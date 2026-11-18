"""Tests for errors.py."""

from __future__ import annotations

from agent_runner.errors import RunnerError
from agent_runner.schema import SchemaError


def test_a_runner_error_carries_its_status() -> None:
    assert RunnerError("nope").status == 400
    e = RunnerError("gone", 404)
    assert (str(e), e.status) == ("gone", 404)


def test_a_body_that_does_not_fit_is_a_400_naming_the_field() -> None:
    e = RunnerError.bad_request(SchemaError("env.A", "must be a string"))
    assert (str(e), e.status) == ("env.A: must be a string", 400)
