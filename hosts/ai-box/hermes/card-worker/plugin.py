"""card-worker: Hermes kanban cards assigned to `coder` are worked by the agent runner's
`agent kanban-worker` (nix-config hosts/ai-box/hermes/card-worker).

Hermes has no worker-runtime hook (NousResearch/hermes-agent#146543 proposes one), so this
replaces the one function its dispatcher asks for a worker's command line. Every card keeps
Hermes's own claim, environment (the run's grant), systemd scope and worker log; only a `coder`
card's command is ours, from command.json beside this file. The system build's contract check
(./contract.py) fails when a Hermes release changes this seam.
"""

import json
from collections.abc import Callable
from pathlib import Path

from hermes_cli import kanban_db_dispatch

ASSIGNEE = "coder"
COMMAND: list[str] = json.loads(Path(__file__).with_name("command.json").read_text())
# Hermes's own, saved once, at import: every card but a coder card gets it.
hermes_worker_argv: Callable[[object, str, str | None], list[str]] = (
    kanban_db_dispatch._worker_argv
)


def worker_argv(task: object, profile_arg: str, hermes_home: str | None) -> list[str]:
    if profile_arg == ASSIGNEE:
        return list(COMMAND)
    return hermes_worker_argv(task, profile_arg, hermes_home)


def register(ctx: object) -> None:
    kanban_db_dispatch._worker_argv = worker_argv
