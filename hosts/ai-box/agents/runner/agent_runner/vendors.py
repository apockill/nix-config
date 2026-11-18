"""Where the agents differ: chosen by what each advertises over ACP or by the agents file, never
by the agent's name.

- Claude Code: its folder trust (the agents file's claude_trust_file), models as a config option,
  steering (`_session/steering`, advertised in initialize's `_meta`).
- Antigravity: models as session models, no steering (messages queue), resume by session/load.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path

from .acp import SessionSetup, SetConfigOptionParams, SetModelParams
from .errors import RunnerError
from .schema import JsonValue
from .store import write_private


def trust_folder(conf: Path, folder: str) -> None:
    """Mark a folder trusted in Claude Code's .claude.json.

    Untrusted, the SDK route loads a project's deny rules but not its allow rules, and nothing
    would ever show the trust dialog.
    """
    data: JsonValue = json.loads(conf.read_text()) if conf.exists() else {}
    if not isinstance(data, dict):
        raise ValueError(f"{conf} isn't a JSON object")
    projects = data.setdefault("projects", {})
    if not isinstance(projects, dict):
        raise ValueError(f"{conf}: projects isn't an object")
    entry = projects.setdefault(folder, {})
    if not isinstance(entry, dict):
        raise ValueError(f"{conf}: projects[{folder!r}] isn't an object")
    if entry.get("hasTrustDialogAccepted") is True:
        return
    entry["hasTrustDialogAccepted"] = True
    write_private(conf, json.dumps(data, indent=2, ensure_ascii=False) + "\n")


def transcript_path(template: str | None, session_id: str, cwd: str) -> str | None:
    """The agent's transcript of a session, from the agents file's template."""
    if not template:
        return None
    return template.format(
        session_id=session_id, cwd=cwd, cwd_slug=re.sub(r"[^A-Za-z0-9]", "-", cwd)
    )


@dataclass(frozen=True)
class ModelChoice:
    """The request that sets a session's model."""

    method: str
    params: SetConfigOptionParams | SetModelParams


def choose_model(
    agent: str, setup: SessionSetup, session_id: str, model: str
) -> ModelChoice:
    """How to give this session `model`: by its config option (Claude) or its models (agy)."""
    option = next(
        (o for o in setup.config_options or [] if o.category == "model"), None
    )
    if option:
        return ModelChoice(
            "session/set_config_option",
            SetConfigOptionParams(session_id, option.id, model),
        )
    if setup.models:
        available = [m.model_id for m in setup.models.available_models]
        if model not in available:
            raise RunnerError(
                f"{agent} has no model {model!r}; it has: {', '.join(available)}"
            )
        return ModelChoice("session/set_model", SetModelParams(session_id, model))
    raise RunnerError(f"{agent} offers no model choice over ACP")
