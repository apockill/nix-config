"""Cron monitor source for the profile canary. It only reads the collector's summary.txt, whose
text stays the same while nothing changes, so the cron model runs only when it does."""

from __future__ import annotations

import os
import time
from pathlib import Path

SUMMARY = (
    Path(os.environ.get("PROFILE_CANARY_DIR", "/var/lib/bambu-profile-canary"))
    / "summary.txt"
)
# The collector runs daily; a summary older than 3 days means it has stopped.
STALE_SECONDS = 3 * 24 * 60 * 60  # 3 days


def main() -> None:
    try:
        age = time.time() - SUMMARY.stat().st_mtime
        summary = SUMMARY.read_text().strip()
    except OSError:
        print(
            "PROBLEM: no profile canary summary yet (is bambu-profile-canary.timer running?)"
        )
        return
    if age > STALE_SECONDS:
        print(
            "PROBLEM: the profile canary's summary is stale; its daily run isn't running."
        )
    print(summary)


if __name__ == "__main__":
    main()
