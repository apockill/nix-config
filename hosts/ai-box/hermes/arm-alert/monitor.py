"""Cron gate for arm-alert (see ./default.nix): has the arm alerted, or is it stuck?

Prints two lines, for example:

    alert: servo_dropout at 11-19 02:10 - <the alert's message>
    arm: released at its rest at 11-19 02:12; gripper servo silent

`alert:` is the arm's active alert (`box lab-arm alerts`): its kind, when it was raised and
its message, plus `(later also: <kinds>)` for other kinds folded into it while it stays
uncleared, or `none`. `arm:` is where the arm is: `released` (motors off, which happens only
at its rest), `powered at its rest`, `powered out of its rest`, or `STUCK` once it has been
powered out of its rest and still for STUCK_S (STUCK_IN_STRETCH_S while a lab stretch holds
the desk). Nothing in the output ticks on its own, so Hermes's monitor mode runs the agent
only when the alert or the arm's place changes. If lab-arm can't be read the script exits
non-zero, which skips the tick without counting as a change (a restarting lab-arm is no
news; apps-health reports one that stays down).
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any

BIN = "/etc/profiles/per-user/hermes/bin"
ENV = {
    **os.environ,
    "PATH": f"{BIN}:/run/current-system/sw/bin:{os.environ.get('PATH', '')}",
}
SITES = "/var/lib/hermes/sites"
# Held while an agent works with the arm (workspace/bin/lab-stretch); its first line is the job.
STRETCH_OWNER = Path("/var/lib/hermes/workspace/lab-stretch.lock/owner")

# Powered out of its rest and still this long, with no one in a lab stretch: stuck. lab-motion
# docks an arm its silent gripper servo left out of its rest after 120 s (MOTION-81), so by
# then that recovery has had its chance.
STUCK_S = 300
# Inside a lab stretch an agent may pause with the arm out (reading results, waiting on a job).
STUCK_IN_STRETCH_S = 1800
# This close to the rest's firmware angles on every joint J1-J6: at its rest (lab-motion's
# AUTO_REST_TOL_RAD).
REST_TOL_DEG = 3.0
MSG_CHARS = 200


def box_json(*args: str) -> Any:
    r = subprocess.run(
        [f"{BIN}/box", "lab-arm", *args, "--json"],
        cwd=SITES,
        env=ENV,
        capture_output=True,
        text=True,
        timeout=60,
    )
    if r.returncode != 0:
        raise RuntimeError(f"box lab-arm {' '.join(args)}: {r.stderr.strip()[:300]}")
    return json.loads(r.stdout)


def stamp(t: float) -> str:
    return time.strftime("%m-%d %H:%M", time.localtime(t))


def epoch(entry: dict[str, Any]) -> float | None:
    """When an alert or event happened: its `t`, else its `at` (ISO with offset)."""
    if isinstance(entry.get("t"), (int, float)):
        return float(entry["t"])
    try:
        return datetime.strptime(entry["at"], "%Y-%m-%dT%H:%M:%S%z").timestamp()
    except (KeyError, TypeError, ValueError):
        return None


def alert_line(alert: dict[str, Any] | None) -> str:
    if not alert:
        return "alert: none"
    t = epoch(alert)
    kind = alert.get("kind", "?")
    later = sorted({a.get("kind", "?") for a in alert.get("also") or []} - {kind})
    msg = " ".join(str(alert.get("msg", "")).split())[:MSG_CHARS]
    return (
        f"alert: {kind} at {stamp(t) if t else alert.get('at', '?')}"
        + (f" (later also: {', '.join(later)})" if later else "")
        + f" - {msg}"
    )


def away_from_rest(angles: list[float], rest_deg: list[float]) -> list[str]:
    """The joints J1-J6 more than REST_TOL_DEG from the rest, e.g. ["J2", "J5"]."""
    return [
        f"J{j + 1}"
        for j in range(6)
        if abs(float(angles[j]) - float(rest_deg[j])) > REST_TOL_DEG
    ]


def still_since(st: dict[str, Any], now: float) -> float | None:
    """Since when the arm hasn't moved: its last move's start, or lab-arm's link coming up
    if it made none since. None while a move runs."""
    move = st.get("move") or {}
    if move.get("state") == "running":
        return None
    t = epoch(move)
    if t is not None:
        return t
    return now - float(st.get("connected_for_s") or 0.0)


def last_release(events: list[dict[str, Any]]) -> float | None:
    """When the arm was last released at its rest (its ARM-70 event)."""
    times = [
        epoch(e)
        for e in events
        if str(e.get("msg", "")).startswith("released at the rest pose")
    ]
    return max((t for t in times if t is not None), default=None)


def arm_line(
    st: dict[str, Any],
    rest_deg: list[float],
    events: list[dict[str, Any]],
    stretch: str | None,
    now: float,
) -> str:
    gripper = (st.get("bus") or {}).get("gripper")
    tail = "; gripper servo silent" if gripper == "missing" else ""
    if st.get("power") not in (0, 1):
        return f"arm: unknown, lab-arm's link to it is {st.get('connection')}"
    if st.get("power") == 0:
        released = last_release(events)
        return f"arm: released at its rest{f' at {stamp(released)}' if released else ''}{tail}"
    away = away_from_rest(st.get("angles") or [], rest_deg)
    if not away:
        return f"arm: powered at its rest{tail}"
    since = still_since(st, now)
    limit = STUCK_IN_STRETCH_S if stretch else STUCK_S
    if since is None or now - since < limit:
        return f"arm: powered out of its rest{tail}"
    held = f"; lab stretch held by {stretch}" if stretch else "; no lab stretch held"
    return (
        f"arm: STUCK powered out of its rest and still since {stamp(since)}"
        f" ({', '.join(away)} away from its rest){tail}{held}"
    )


def stretch_holder() -> str | None:
    try:
        return STRETCH_OWNER.read_text().splitlines()[0].strip() or "?"
    except (OSError, IndexError):
        return None


def main() -> int:
    try:
        st = box_json("state")["state"]
        alert = box_json("alerts").get("alert")
        rest_deg = box_json("rest")["firmware_deg"]
        events = box_json("events", "--limit", "1000").get("events") or []
        if st.get("power") not in (0, 1) and st.get("connection") == "connected":
            raise ValueError(
                f"its power reads {st.get('power')!r}"
            )  # a stale read: next tick
    except (
        OSError,
        RuntimeError,
        subprocess.TimeoutExpired,
        ValueError,
        KeyError,
        TypeError,
    ) as e:
        print(f"arm-alert: can't read lab-arm: {e}", file=sys.stderr)
        return 1
    print(alert_line(alert))
    print(arm_line(st, rest_deg, events, stretch_holder(), time.time()))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
