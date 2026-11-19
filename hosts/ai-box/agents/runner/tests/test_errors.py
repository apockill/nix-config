"""Tests for errors.py."""

from __future__ import annotations

import pytest
from agent_runner.base import Strict
from agent_runner.errors import RunnerError
from pydantic import ValidationError


class Body(Strict):
    env: dict[str, str]


def test_a_runner_error_carries_its_status() -> None:
    assert RunnerError("nope").status == 400
    e = RunnerError("gone", 404)
    assert (str(e), e.status) == ("gone", 404)


def test_a_body_that_does_not_fit_is_a_400_naming_the_field() -> None:
    with pytest.raises(ValidationError) as caught:
        Body.model_validate({"env": {"A": 1}})
    e = RunnerError.bad_request(caught.value)
    assert e.status == 400
    assert str(e) == "env.A: Input should be a valid string"
