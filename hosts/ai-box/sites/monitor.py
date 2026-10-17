"""Cron monitor source for app health (see hosts/ai-box/sites/runner.nix).

Prints a stable summary of anything that needs Alex. Hermes runs the cron
model only when this output changes, so it must not contain timestamps or
anything else that changes on its own. Healthy or self-healed apps print
nothing; they show up only on the portal status page.
"""

import json
import os
import time

STATE = os.environ.get("APPS_HEALTH_DIR", "/var/lib/apps-health")
STALE_S = 300

try:
    with open(f"{STATE}/status.json") as f:
        status = json.load(f)
except (OSError, ValueError):
    print("PROBLEM: apps runner has no status file (is ai-box-apps-runner running?)")
    raise SystemExit(0) from None

problems = []
if time.time() - status.get("heartbeat", 0) > STALE_S:
    problems.append(
        "PROBLEM: apps runner heartbeat is stale; the supervisor is not running, "
        "so nothing is being healed."
    )

failed = {
    n: a for n, a in status.get("apps", {}).items() if a.get("status") == "failed"
}
if failed:
    last = {}
    try:
        with open(f"{STATE}/events.jsonl") as f:
            for line in f:
                e = json.loads(line)
                if (
                    e.get("event") == "status"
                    and e.get("status") == "failed"
                    and "restarts" in e
                ):
                    last[e["app"]] = e
    except (OSError, ValueError):
        pass
    for name, a in sorted(failed.items()):
        e = last.get(name, {})
        problems.append(
            f"FAILED: {name} ({name}.alexthiele.io). Auto-healing gave up "
            f"after {e.get('restarts', '?')} restarts in an hour. "
            f"Last reason: {a.get('reason') or e.get('reason', 'unknown')}"
        )
        if e.get("log"):
            problems.append(
                "  last log lines:\n"
                + "\n".join("    " + log_line for log_line in e["log"])
            )

print("\n".join(problems) if problems else "OK: no app needs attention")
