"""agents-usage-digest: the last day's Claude usage on ai-box, as alert states (./default.nix).

It reads every Claude transcript written in the last day (~/.claude/projects, subagents
included), counts each API request once (by requestId), and the runner's sessions
(`agent list --json`). It prints one line per alert, `ok <alert>: ...` or `ALERT <alert>: ...`,
and nothing that drifts from day to day while the state holds, so Hermes's monitor mode runs the
model only when an alert starts or ends. `--details` adds the numbers (for whoever investigates).

The alerts (SKEPTIC.md, "Drift", point 3):
- cache-hit: cache reads under 95% of all input, i.e. the prompt cache stopped working.
- api-errors: Claude Code's own error messages (model `<synthetic>`, `isApiErrorMessage`):
  any with `error: rate_limit` (a usage limit), or 20 or more of any kind (a retry loop, as on
  2026-11-15). Read from those fields, never from the message's wording.
- idle-sessions: runner sessions with their agent up and nothing for 24 h.
- notify: runner sessions whose last notice to Alex failed (`notify_error`: notify-alex itself
  broke, so nothing else would say so).

Big contexts are no alert: how much of the reads come from contexts above 400k tokens is only in
`--details`, as a number. Context size is what the agents need; a smaller compaction window to
cut it costs agent quality, and that needs Alex's skeptical review, not a nudge from a cron.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from collections import Counter
from collections.abc import Iterable, Iterator
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

DAY = 24 * 3600.0
HIT_RATIO = 0.95
BIG_CONTEXT = 400_000
ERROR_LOOP = 20
IDLE_SECONDS = DAY


@dataclass
class Tally:
    """One day's requests: tokens by kind, and the reads of big contexts."""

    requests: dict[str, tuple[int, int, int]] = field(default_factory=dict)
    errors: Counter[str] = field(default_factory=Counter)
    error_ids: set[str] = field(default_factory=set)

    def add(self, record: dict[str, Any], since: float) -> None:
        message = record.get("message")
        if record.get("type") != "assistant" or not isinstance(message, dict):
            return
        if stamp(record) < since:
            return
        if message.get("model") == "<synthetic>":
            uuid = str(record.get("uuid"))
            if record.get("isApiErrorMessage") and uuid not in self.error_ids:
                self.error_ids.add(uuid)
                self.errors[str(record.get("error") or "unknown")] += 1
            return
        request_id, usage = record.get("requestId"), message.get("usage")
        if isinstance(request_id, str) and isinstance(usage, dict):
            self.requests[request_id] = (
                int(usage.get("input_tokens") or 0),
                int(usage.get("cache_creation_input_tokens") or 0),
                int(usage.get("cache_read_input_tokens") or 0),
            )

    @property
    def reads(self) -> int:
        return sum(r for _, _, r in self.requests.values())

    @property
    def total_input(self) -> int:
        return sum(i + w + r for i, w, r in self.requests.values())

    @property
    def big_reads(self) -> int:
        return sum(r for i, w, r in self.requests.values() if i + w + r > BIG_CONTEXT)


def stamp(record: dict[str, Any]) -> float:
    value = record.get("timestamp")
    if not isinstance(value, str):
        return 0.0
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()
    except ValueError:
        return 0.0


def transcripts(projects: Path, since: float) -> Iterator[Path]:
    for path in projects.rglob("*.jsonl"):
        try:
            if path.stat().st_mtime >= since:
                yield path
        except OSError:
            continue


def read(path: Path) -> Iterator[dict[str, Any]]:
    with path.open(errors="replace") as f:
        for line in f:
            # Most lines are neither; skip them before parsing.
            if '"assistant"' not in line:
                continue
            try:
                value = json.loads(line)
            except ValueError:
                continue
            if isinstance(value, dict):
                yield value


def tally(paths: Iterable[Path], since: float) -> Tally:
    t = Tally()
    for path in paths:
        for record in read(path):
            t.add(record, since)
    return t


def idle_sessions(sessions: Iterable[dict[str, Any]], now: float) -> list[str]:
    return sorted(
        str(s["name"])
        for s in sessions
        if s.get("alive")
        and s.get("state") == "idle"
        and now - float(s.get("last_event_at") or 0) > IDLE_SECONDS
    )


def unnotified(sessions: Iterable[dict[str, Any]]) -> list[str]:
    """The sessions whose last notice to Alex failed."""
    return sorted(str(s["name"]) for s in sessions if s.get("notify_error"))


def alerts(
    t: Tally, idle: list[str] | None, unnotified: list[str] | None = None
) -> list[str]:
    """The alert lines; `idle` and `unnotified` are None when the runner couldn't be asked."""
    lines = []
    if not t.requests:
        lines.append("ok cache-hit: no requests")
    else:
        hit = t.reads / t.total_input if t.total_input else 1.0
        lines.append(
            "ok cache-hit: at least 95% of input read from cache"
            if hit >= HIT_RATIO
            else "ALERT cache-hit: under 95% of input read from cache"
        )
    limits, total = t.errors.get("rate_limit", 0), sum(t.errors.values())
    if limits:
        lines.append(
            "ALERT api-errors: usage-limit errors (rate_limit) in the last day"
        )
    elif total >= ERROR_LOOP:
        lines.append(
            f"ALERT api-errors: {ERROR_LOOP} or more API error messages in the last day"
        )
    else:
        lines.append("ok api-errors: no usage limit, no error loop")
    if idle is None:
        lines.append(
            "ALERT idle-sessions: can't list the runner's sessions (is agent-runner up?)"
        )
    elif idle:
        lines.append(f"ALERT idle-sessions: {', '.join(idle)} idle over 24 h")
    else:
        lines.append("ok idle-sessions: none idle over 24 h")
    if unnotified:
        lines.append(f"ALERT notify: telling Alex failed for {', '.join(unnotified)}")
    elif unnotified is not None:
        lines.append("ok notify: no failed notices")
    return lines


def details(t: Tally) -> list[str]:
    hit = t.reads / t.total_input if t.total_input else 0.0
    share = t.big_reads / t.reads if t.reads else 0.0
    errors = ", ".join(f"{k} {v}" for k, v in t.errors.most_common()) or "none"
    return [
        f"requests: {len(t.requests)}; input {t.total_input:,} tokens, cache reads {t.reads:,}",
        f"cache-hit ratio: {hit:.1%}; reads above 400k: {share:.1%}",
        f"API error messages: {errors}",
    ]


def runner_sessions(agent: str) -> list[dict[str, Any]]:
    out = subprocess.run(
        [agent, "list", "--json"], capture_output=True, text=True, timeout=60
    )
    if out.returncode:
        raise RuntimeError(f"agent list: {out.stderr.strip()[:300]}")
    sessions: list[dict[str, Any]] = json.loads(out.stdout)
    return sessions


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--projects", type=Path, required=True, help="~/.claude/projects")
    p.add_argument("--agent", required=True, help="the runner's CLI (agent)")
    p.add_argument("--details", action="store_true", help="add the numbers")
    a = p.parse_args(argv)
    now = time.time()
    t = tally(transcripts(a.projects, now - DAY), now - DAY)
    idle: list[str] | None = None
    failed: list[str] | None = None
    try:
        sessions = runner_sessions(a.agent)
        idle, failed = idle_sessions(sessions, now), unnotified(sessions)
    except (OSError, RuntimeError, ValueError, subprocess.SubprocessError) as e:
        why = str(e)
    lines = alerts(t, idle, failed)
    if a.details:
        lines += details(t) + ([] if idle is not None else [f"runner: {why}"])
    print("\n".join(lines))
    return 0


if __name__ == "__main__":
    sys.exit(main())
