"""Cron monitor source for the state audit. Output is stable (no timestamps),
so the cron model runs only when the set of undeclared paths changes."""

import os
import time
from pathlib import Path

SUMMARY = (
    Path(os.environ.get("STATE_AUDIT_DIR", "/var/lib/state-audit")) / "summary.txt"
)
# The audit runs hourly; a report older than 3 hours means it has stopped.
STALE_SECONDS = 3 * 60 * 60  # 3 hours


def main() -> None:
    try:
        age = time.time() - SUMMARY.stat().st_mtime
        summary = SUMMARY.read_text().strip()
    except OSError:
        print("PROBLEM: no state-audit report yet (is state-audit.timer running?)")
        return
    if age > STALE_SECONDS:
        print(
            "PROBLEM: the state-audit report is stale; the hourly audit isn't running."
        )
    print(summary)


if __name__ == "__main__":
    main()
