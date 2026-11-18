"""The runner's expected failures."""

from __future__ import annotations

from .schema import SchemaError


class RunnerError(Exception):
    """An expected failure, reported to the API's caller with an HTTP status."""

    def __init__(self, message: str, status: int = 400) -> None:
        super().__init__(message)
        self.status = status

    @classmethod
    def bad_request(cls, error: SchemaError) -> RunnerError:
        """A request body that doesn't fit its schema: a 400 naming the field."""
        return cls(str(error), 400)
