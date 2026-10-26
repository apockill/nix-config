"""desk-idle: put the desk to sleep when nobody is using it (Alex, 2026-10-26).

Runs hourly. If anything is still awake (arm powered, projector or desk light on), it
gathers what's going on, shows Gemma the facts and an overhead photo, and lets Gemma
decide. On "shut down": dock the arm on its rest (motors released), projector plug off,
desk light off, then tell Alex on Discord. When it decides not to, it stays silent.
"""

import base64
import json
import re
import subprocess
import sys
import time
import urllib.request
from pathlib import Path
from typing import Any

LLM = "http://127.0.0.1:8080/v1/chat/completions"
MODEL = "gemma-4-26b-a4b"
SNAP = Path("/var/lib/hermes/.hermes/cache/desk-idle-top.jpg")
TRANSCRIPTS = Path("/var/lib/hermes/.claude/projects/-var-lib-hermes-sites-desklab")


def box(*args: str, timeout: float = 120) -> Any:
    r = subprocess.run(
        ["box", *args, "--json"], capture_output=True, text=True, timeout=timeout
    )
    if r.returncode != 0:
        return {"error": (r.stderr or r.stdout).strip()[:200]}
    try:
        return json.loads(r.stdout)
    except ValueError:
        return {"error": r.stdout.strip()[:200]}


def minutes_ago(t: float | None) -> float | None:
    return None if t is None else round((time.time() - t) / 60, 1)


def facts() -> dict[str, Any]:
    arm = box("desklab", "arm", "state")
    events = box("desklab", "arm", "events")
    moves = (
        [
            e
            for e in events
            if isinstance(e, dict) and e.get("kind") in ("command", "move")
        ]
        if isinstance(events, list)
        else []
    )
    switches = box("matter", "switches")
    plugs = {s["name"]: s["id"] for s in switches} if isinstance(switches, list) else {}
    on = (
        {s["name"]: bool(s.get("state", {}).get("on")) for s in switches}
        if isinstance(switches, list)
        else {}
    )
    state = {}
    for name, cmd in (("hover_session", ("hover", "session")), ("experiment", ("experiment",)),
                      ("calibration", ("calibrate", "status")), ("scan3d", ("scan3d", "status"))):  # fmt: skip
        d = box("desklab", *cmd)
        state[name] = (
            d.get("state") if isinstance(d, dict) and "error" not in d else None
        )
    newest = max((p.stat().st_mtime for p in TRANSCRIPTS.glob("*.jsonl")), default=None)
    return {
        "local_time": time.strftime("%a %H:%M"),
        "arm_powered": isinstance(arm, dict) and arm.get("power") == 1,
        "minutes_since_last_arm_command": minutes_ago(
            moves[-1].get("t") if moves else None
        ),
        "desk_light_on": on.get("Desk light"),
        "projector_on": on.get("Projector"),
        "desklab_activities": state,
        "minutes_since_claude_code_worked_in_desklab": minutes_ago(newest),
        "_plugs": plugs,
    }


def snapshot() -> str | None:
    # The room as it is (no light switched on for it): at night Gemma may see little.
    r = subprocess.run(
        ["box", "desklab", "cameras", "snapshot", "top", "-o", str(SNAP)],
        capture_output=True,
        timeout=60,
    )
    return (
        base64.b64encode(SNAP.read_bytes()).decode()
        if r.returncode == 0 and SNAP.exists()
        else None
    )


def decide(f: dict[str, Any], img: str | None) -> tuple[bool, str]:
    shown = {k: v for k, v in f.items() if not k.startswith("_")}
    text = (
        "You decide whether to put Alex's desk robotics workstation to sleep. Sleep means: dock the robot "
        "arm on its rest and release its motors, switch off the projector and the desk light.\n"
        "Check:\n"
        "- Is any desklab activity running or waiting (states like running, waiting, needs_alex, needs_attention)?\n"
        "- Did anyone command the arm in the last 60 minutes?\n"
        "- Did a Claude Code job work in desklab in the last 60 minutes?\n"
        "- In the overhead photo (if any): is a person, a hand or a human arm at the desk? (The robot arm, "
        "cameras, a foam block and paper are normal.)\n"
        "Sleep only if all of these say nobody is using it. When unsure, don't.\n"
        'Answer with JSON only: {"sleep": true|false, "reason": "<= 20 words"}\n\n'
        f"Facts: {json.dumps(shown)}"
    )
    content: list[dict[str, Any]] = [{"type": "text", "text": text}]
    if img:
        content.append(
            {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{img}"}}
        )
    req = {"model": MODEL, "temperature": 0, "max_tokens": 300, "messages": [{"role": "user", "content": content}],
           "chat_template_kwargs": {"enable_thinking": False}}  # fmt: skip
    r = urllib.request.Request(
        LLM, json.dumps(req).encode(), {"Content-Type": "application/json"}
    )
    with urllib.request.urlopen(r, timeout=300) as resp:
        out = json.loads(resp.read())["choices"][0]["message"].get("content") or ""
    m = re.search(r"\{.*\}", out, re.S)
    if not m:
        return False, f"unparseable: {out[:80]!r}"
    d = json.loads(m.group(0))
    return bool(d.get("sleep")), str(d.get("reason", ""))


def notify(text: str) -> None:
    subprocess.run(["notify-alex", text], timeout=60)


def sleep_desk(f: dict[str, Any], reason: str) -> None:
    done, problems = [], []
    if f["arm_powered"]:
        d = box("desklab", "hover", "session", "dock", "--by", "desk-idle")
        if "error" in d:
            problems.append(f"dock refused: {d['error']}")
        else:
            for _ in range(120):
                time.sleep(5)
                s = box("desklab", "hover", "session")
                if s.get("state") != "running":
                    break
            if s.get("state") == "done":
                done.append("arm docked, motors released")
            else:
                problems.append(
                    f"dock ended {s.get('state')}: {s.get('why')} (the arm holds where it stopped)"
                )
    if f["desk_light_on"]:
        r = subprocess.run(
            ["box", "desklab", "lights", "off"], capture_output=True, text=True
        )
        (done if r.returncode == 0 else problems).append(
            "desk light off" if r.returncode == 0 else f"light: {r.stderr[:100]}"
        )
    if f["projector_on"] and "Projector" in f["_plugs"]:
        r = subprocess.run(
            ["box", "matter", "switches", "off", f["_plugs"]["Projector"]],
            capture_output=True,
            text=True,
        )
        (done if r.returncode == 0 else problems).append(
            "projector off" if r.returncode == 0 else f"projector: {r.stderr[:100]}"
        )
    msg = f"Desk idle, put it to sleep ({reason}): " + ", ".join(
        done or ["nothing changed"]
    )
    if problems:
        msg += ". PROBLEM: " + "; ".join(problems)
    notify(msg)


def main() -> None:
    f = facts()
    if not (f["arm_powered"] or f["desk_light_on"] or f["projector_on"]):
        print("already asleep")
        return
    go, reason = decide(f, snapshot())
    print(json.dumps({k: v for k, v in f.items() if not k.startswith("_")}), go, reason)
    if go and "--dry-run" not in sys.argv:
        sleep_desk(f, reason)


if __name__ == "__main__":
    main()
