"""The runner's expected failures."""

from __future__ import annotations

from pydantic import ValidationError

from .base import describe


class RunnerError(Exception):
    """An expected failure, reported to the API's caller with an HTTP status."""

    def __init__(self, message: str, status: int = 400) -> None:
        super().__init__(message)
        self.status = status

    @classmethod
    def bad_request(cls, error: ValidationError) -> RunnerError:
        """A request body that doesn't fit its model: a 400 naming the field."""
        return cls(describe(error), 400)
