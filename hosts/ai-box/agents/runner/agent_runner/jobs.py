"""Jobs: what the CLI adds to the API.

A job is a session named after its title (`slug`), started from a task file as its first message,
with the starter's PATH and temp folder (PASSED_ENV).
"""

from __future__ import annotations

import json
import os
import re
import string
from collections.abc import Mapping
from pathlib import Path

from .api_types import StartRequest
from .base import JsonObject, JsonValue, Strict

# Everything a job gets of its starter's environment: the tools it sees, and its temp folder.
PASSED_ENV = ("PATH", "TMPDIR")


class JobError(Exception):
    """A job the CLI won't start or can't reach; the message says why."""


def slug(title: str) -> str:
    """The session name for a job title: lowercase ASCII letters, digits and dashes."""
    lower = title.translate(
        str.maketrans(string.ascii_uppercase, string.ascii_lowercase)
    )
    return re.sub(r"[^a-z0-9]+", "-", lower).strip("-")[:63].rstrip("-")


def read_task(path: str) -> str:
    try:
        return os.fsdecode(Path(path).read_bytes()).rstrip("\n")
    except OSError as e:
        raise JobError(f"can't read the task file {path}: {e.strerror}") from e


class JobSpec(Strict):
    """`agent start`'s arguments."""

    title: str
    dir: str
    task_file: str | None = None
    task: str | None = None
    agent: str | None = None
    model: str | None = None
    mode: str | None = None
    resume: str | None = None
    env: tuple[tuple[str, str], ...] = ()
    origin: str | None = None
    session_meta: JsonObject | None = None
    allow_runner: bool = False


def start_request(spec: JobSpec, environ: Mapping[str, str]) -> StartRequest:
    """The session for a job; JobError if its title, folder or task file won't do."""
    name = slug(spec.title)
    if not name:
        raise JobError(f"the title {spec.title!r} needs a letter or digit")
    folder = Path(spec.dir)
    if not folder.is_dir():
        raise JobError(f"{spec.dir} isn't a directory")
    task = read_task(spec.task_file) if spec.task_file else spec.task
    env = {k: v for k in PASSED_ENV if (v := environ.get(k))}
    env.update(dict(spec.env))
    return StartRequest(
        name=name,
        dir=str(folder.resolve()),
        task=task,
        agent=spec.agent,
        model=spec.model,
        mode=spec.mode,
        resume=spec.resume,
        env=env,
        origin=spec.origin or f"job: {spec.title}",
        session_meta=spec.session_meta,
        allow_runner=spec.allow_runner or None,
    )


def answer_body(
    request_id: str, value: str | None, decline: bool, cancel: bool
) -> JsonObject:
    """The answer to a parked request: p<n> takes an option id, q<n> the form's fields as JSON."""
    if request_id.startswith("p"):
        if cancel:
            return {"cancel": True}
        if decline or not value:
            raise JobError(f"{request_id} takes an option id (see peek) or --cancel")
        return {"option_id": value}
    if request_id.startswith("q"):
        if cancel or decline:
            return {"action": "cancel" if cancel else "decline"}
        if not value:
            raise JobError(
                f"{request_id} takes the form's fields as JSON, --decline or --cancel"
            )
        try:
            content: JsonValue = json.loads(value)
        except ValueError as e:
            raise JobError(f"{request_id}: the answer isn't JSON: {e}") from e
        return {"action": "accept", "content": content}
    raise JobError(f"{request_id} isn't a request id (p1, q1, ...; see peek)")
