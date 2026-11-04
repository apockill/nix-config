"""Tests for reset-plan.nix, evaluated with `nix eval`: on made-up
declarations, and on ai-box's real ones. Run with `just test`."""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

HERE = Path(__file__).parent
REPO = HERE.parents[2]
AI_BOX = f"{REPO}#nixosConfigurations.ai-box"

pytestmark = pytest.mark.skipif(shutil.which("nix") is None, reason="needs nix")


def nix_eval(attr: str, apply: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["nix", "eval", "--impure", "--json", attr, "--apply", apply],
        capture_output=True,
        text=True,
    )


def plan_for(declared: dict[str, str]) -> list[tuple[str, str]]:
    """The plan for `declared` ({path: backup class})."""
    paths = {p: {"backup": backup} for p, backup in declared.items()}
    result = nix_eval(
        f"{AI_BOX}.pkgs.lib",
        f"lib: import {HERE / 'reset-plan.nix'} {{ inherit lib; }} "
        f"(builtins.fromJSON {json.dumps(json.dumps(paths))})",
    )
    assert result.returncode == 0, result.stderr
    return [(step["action"], step["path"]) for step in json.loads(result.stdout)]


def test_nesting_at_any_depth_is_copy_delete_copy() -> None:
    assert plan_for(
        {
            "/a": "restic",
            "/a/b": "ephemeral",
            "/a/b/c": "cache",
            "/a/b/c/d": "ephemeral",
            "/a/x": "cache",  # inside a kept path: copied with it
            "/tmp": "ephemeral",  # nothing kept around it: nothing to do
            "/tmp/keep": "host",
        }
    ) == [
        ("copy", "/a"),
        ("delete", "/a/b"),
        ("copy", "/tmp/keep"),
        ("copy", "/a/b/c"),
        ("delete", "/a/b/c/d"),
    ]


def test_star_segments_match_ancestors() -> None:
    assert plan_for(
        {
            "/sites": "git",
            "/sites/*/state": "restic",
            "/sites/*/state/cache": "ephemeral",
            "/home/*": "ephemeral",
            "/home/alex/keep": "restic",
        }
    ) == [
        ("copy", "/sites"),
        ("copy", "/home/alex/keep"),
        ("delete", "/sites/*/state/cache"),
    ]


def test_overlapping_kept_and_ephemeral_declarations_are_refused() -> None:
    paths = {"/x/*": {"backup": "ephemeral"}, "/x/a": {"backup": "restic"}}
    result = nix_eval(
        f"{AI_BOX}.pkgs.lib",
        f"lib: import {HERE / 'reset-plan.nix'} {{ inherit lib; }} "
        f"(builtins.fromJSON {json.dumps(json.dumps(paths))})",
    )
    assert result.returncode != 0
    assert '"/x/*" and "/x/a" can name the same path' in result.stderr


def test_ai_box_plan() -> None:
    result = nix_eval(
        f"{AI_BOX}.config.aiBox.state.resetPlan",
        "plan: map (step: [ step.action step.path ]) plan",
    )
    assert result.returncode == 0, result.stderr
    plan = [tuple(step) for step in json.loads(result.stdout)]
    hermes = "/var/lib/hermes"

    assert ("copy", f"{hermes}/.hermes") in plan
    assert ("delete", f"{hermes}/.hermes/config.yaml") in plan
    assert ("copy", f"{hermes}/sites") in plan
    assert ("copy", "/var/cache/private/llama-cpp") in plan  # in ephemeral /var/cache
    assert ("copy", "/etc/machine-id") in plan
    paths = [path for _, path in plan]
    # Ephemeral with nothing kept around it, or inside a kept path.
    for absent in (
        "/tmp",
        "/var/cache",
        "/var/lib/root-reset",
        f"{hermes}/.pki",
        f"{hermes}/workspace/nix-config",
        f"{hermes}/sites/*/state",
    ):
        assert absent not in paths
    depths = [path.count("/") for path in paths]
    assert depths == sorted(depths)
