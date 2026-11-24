"""agents-canary: checks, live, what the agent runner assumes about its vendors (./default.nix).

It starts a private agent runner (the runner package's `agent serve`, its own socket and state in a
temp folder, nobody notified) on the box's agents file and subscription, runs a short Claude Haiku
session through it, restarts it, resumes the session, and reads what Claude wrote: its transcript
records the API requests themselves (`api-request`: model, betas; `api-request-shape`: the system
prompt; `api-request-blob`: the messages), so no proxy is needed. Antigravity gets one Flash turn
when it is signed in.

Each check prints one line, `ok <check>[: <what>]`, `FAIL <check>: <why>` or `skip <check>: <why>`,
with nothing in it that changes from run to run (no times, token counts or paths), so Hermes's
monitor mode wakes the model only when an assumption breaks or a version moves. It exits 0 when
the checks ran, whatever they found; 1 (with a `FAIL canary: ...` line) when it couldn't run.
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import tempfile
import time
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from evidence import (
    OAUTH_BETA,
    REPO_SENTINEL,
    SHELL_CHECK,
    CanaryError,
    Check,
    agent_info,
    auth_kinds,
    betas,
    cache_covers,
    cli_versions,
    fail,
    first_request_text,
    main_requests,
    occurrences,
    ok,
    permission_modes,
    question_schema,
    read_secrets,
    records,
    sentinel_of,
    shell_outputs,
    skip,
    transcript_of,
)
from private_runner import Runner

# --- The checks ---------------------------------------------------------------------------------


@dataclass(frozen=True)
class Setup:
    agent: str
    instructions: Path
    secrets: Path
    pass_env: list[str]
    home: str
    agy_token: Path
    work: Path


def base_env(setup: Setup) -> dict[str, str]:
    """What agent-runner.service runs with (agents/runner/default.nix), and the sign-ins."""
    try:
        text = setup.secrets.read_text()
    except OSError as e:
        raise CanaryError(f"can't read the secrets file: {e.strerror}") from e
    found = read_secrets(text, setup.pass_env)
    if missing := [n for n in setup.pass_env if not found.get(n)]:
        raise CanaryError(f"the secrets file has no {', '.join(missing)}")
    path = f"/run/wrappers/bin:/etc/profiles/per-user/{os.environ.get('USER', 'hermes')}/bin"
    return {
        "PATH": f"{path}:/run/current-system/sw/bin",
        "HOME": setup.home,
        "USER": os.environ.get("USER", "hermes"),
        "LANG": "C.UTF-8",
        "TMPDIR": tempfile.gettempdir(),
        **found,
    }


def make_repo(work: Path) -> Path:
    """The Claude session's folder: the same path every run (one project in ~/.claude)."""
    repo = work / "repo"
    repo.mkdir(parents=True, exist_ok=True)
    (repo / "AGENTS.md").write_text(f"# Canary\n\n{REPO_SENTINEL}\n")
    (repo / "CLAUDE.md").write_text("@AGENTS.md\n")
    return repo


def claude_checks(
    runner: Runner, setup: Setup, repo: Path, secrets: Sequence[str]
) -> list[Check]:
    name = "canary-claude"
    checks: list[Check] = []
    runner.call(
        "POST",
        "/v1/sessions",
        {
            "name": name,
            "dir": str(repo),
            "agent": "claude",
            "model": "haiku",
            "origin": "agents-canary",
            "task": f"Run this shell command and reply with its output only:\n{SHELL_CHECK}",
        },
    )
    runner.wait_turn(name, 0)
    runner.turn(name, "Reply with only the word two.")
    asked = runner.turn(
        name,
        "Use the AskUserQuestion tool once to ask me whether I prefer red or blue, with those two"
        " options. Do nothing else.",
    )
    if asked["kind"] == "question":
        since = runner.latest(name)
        runner.call(
            "POST",
            f"/v1/sessions/{name}/requests/{asked['request_id']}",
            {"action": "decline"},
        )
        runner.wait_turn(name, since)
    events = runner.events(name)
    transcript = transcript_of(events)
    if not transcript or not Path(transcript).is_file():
        return [
            fail(
                "claude-transcript-path",
                "no file where the agents file's template points",
            )
        ]
    checks.append(ok("claude-transcript-path"))
    before = len(main_requests(records(Path(transcript))))
    code = runner.restart()
    runner.turn(name, "Reply with only the word four.")
    events = runner.events(name)
    recs = records(Path(transcript))
    info = agent_info(events)
    versions = sorted(cli_versions(recs))
    checks.append(
        ok(
            "claude-versions",
            f"{info.get('name')} {info.get('version')}, Claude Code {', '.join(versions)}",
        )
    )

    user = occurrences(
        first_request_text(recs), sentinel_of(setup.instructions.read_text())
    )
    repo_count = occurrences(first_request_text(recs), REPO_SENTINEL)
    counts = f"the shared AGENTS.md {user}, the repo's {repo_count}"
    checks.append(
        ok("claude-instructions", "once each")
        if (user, repo_count) == (1, 1)
        else fail("claude-instructions", counts)
    )

    modes = permission_modes(recs)
    checks.append(
        ok("claude-permission-mode", "auto")
        if modes == {"auto"}
        else fail("claude-permission-mode", ", ".join(sorted(modes)) or "none recorded")
    )

    kinds = auth_kinds(events)
    all_betas = betas(recs)
    if kinds == {"account"} and all_betas and all(OAUTH_BETA in b for b in all_betas):
        checks.append(ok("claude-subscription"))
    else:
        oauth = sum(OAUTH_BETA in b for b in all_betas)
        checks.append(
            fail(
                "claude-subscription",
                f"auth status {sorted(kinds)}, {oauth} of {len(all_betas)} requests with {OAUTH_BETA}",
            )
        )

    outputs = shell_outputs(recs)
    files = [
        Path(transcript),
        runner.folder / "state/sessions" / name / "events.jsonl",
        runner.folder / "state/sessions" / name / "agent.log",
    ]
    leaked = [
        f.name
        for f in files
        if f.exists() and any(s and s in f.read_text(errors="replace") for s in secrets)
    ]
    if leaked:
        checks.append(
            fail("claude-token-hidden", f"the token is in {', '.join(leaked)}")
        )
    elif any("CANARY-TOKEN-VISIBLE" in o for o in outputs):
        checks.append(
            fail(
                "claude-token-hidden", "the agent's shell sees CLAUDE_CODE_OAUTH_TOKEN"
            )
        )
    elif any("CANARY-TOKEN-HIDDEN" in o for o in outputs):
        checks.append(ok("claude-token-hidden"))
    else:
        checks.append(
            fail("claude-token-hidden", "the agent didn't run the shell check")
        )

    usage = main_requests(recs)
    if len(usage) < 2 or not cache_covers(usage[0], usage[1]):
        checks.append(
            fail(
                "claude-cache",
                "the second request didn't read the first one's prefix from cache",
            )
        )
    else:
        checks.append(ok("claude-cache"))

    schema = question_schema(events)
    if schema is None:
        checks.append(fail("claude-question", "no question event for AskUserQuestion"))
    elif not isinstance(schema.get("properties"), dict) or not schema["properties"]:
        checks.append(
            fail(
                "claude-question", "the question came without requestedSchema's fields"
            )
        )
    else:
        checks.append(ok("claude-question", "with requestedSchema"))

    if code != 75:
        checks.append(fail("claude-resume", f"restart exited {code}, not 75"))
    elif len(usage) <= before or not cache_covers(usage[before - 1], usage[before]):
        checks.append(
            fail(
                "claude-resume",
                "the first request after the restart didn't read the prefix from cache",
            )
        )
    else:
        checks.append(ok("claude-resume", "reads the prefix after a restart"))
    runner.call("POST", f"/v1/sessions/{name}/stop", {"reason": "canary done"})
    return checks


def agy_checks(runner: Runner, setup: Setup, repo: Path) -> list[Check]:
    if not setup.agy_token.is_file() or not setup.agy_token.stat().st_size:
        return [skip("agy", "not signed in")]
    name = "canary-agy"
    runner.call(
        "POST",
        "/v1/sessions",
        {
            "name": name,
            "dir": str(repo),
            "agent": "antigravity",
            "model": "gemini-3.8-flash-low",
            "origin": "agents-canary",
            "task": "Reply with only the word ready.",
        },
    )
    runner.wait_turn(name, 0)
    time.sleep(10)  # what agy says after end_turn
    events = runner.events(name)
    info = agent_info(events)
    checks = [ok("agy-versions", f"{info.get('name')} {info.get('version')}")]
    transcript = transcript_of(events)
    if transcript and Path(transcript).is_file():
        checks.append(ok("agy-transcript-path"))
    else:
        checks.append(
            fail(
                "agy-transcript-path", "no file where the agents file's template points"
            )
        )
    checks.append(
        skip("agy-after-end-turn", "needs a subagent's result, not automated yet")
    )
    runner.call("POST", f"/v1/sessions/{name}/stop", {"reason": "canary done"})
    return checks


def forget_old_transcripts(home: str, repo: Path) -> None:
    """Keep only the last canary run's Claude transcript."""
    slug = "".join(c if c.isalnum() else "-" for c in str(repo))
    folder = Path(home) / ".claude" / "projects" / slug
    if folder.is_dir():
        for old in folder.glob("*.jsonl"):
            old.unlink()


def run(setup: Setup) -> list[Check]:
    env = base_env(setup)
    secrets = [env[n] for n in setup.pass_env]
    repo = make_repo(setup.work)
    forget_old_transcripts(setup.home, repo)
    folder = Path(tempfile.mkdtemp(prefix="run-", dir=setup.work))
    runner = Runner(setup.agent, folder, env)
    try:
        runner.start()
        return claude_checks(runner, setup, repo, secrets) + agy_checks(
            runner, setup, repo
        )
    finally:
        runner.stop()
        shutil.rmtree(folder, ignore_errors=True)


def main(argv: Sequence[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--agent", required=True, help="the runner's CLI (agent)")
    p.add_argument("--instructions", required=True, type=Path)
    p.add_argument("--secrets", required=True, type=Path)
    p.add_argument("--pass-env", action="append", default=[])
    p.add_argument("--home", required=True)
    p.add_argument("--agy-token", required=True, type=Path)
    p.add_argument(
        "--work", type=Path, default=Path(tempfile.gettempdir()) / "agents-canary"
    )
    a = p.parse_args(argv)
    setup = Setup(
        a.agent, a.instructions, a.secrets, a.pass_env, a.home, a.agy_token, a.work
    )
    try:
        checks = run(setup)
    except (CanaryError, OSError, subprocess.SubprocessError, ValueError) as e:
        print(f"FAIL canary: couldn't run: {e}", flush=True)
        return 1
    for c in checks:
        print(c.line(), flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
