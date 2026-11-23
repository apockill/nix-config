"""The card-worker plugin's contract with Hermes, run by the system build (./default.nix) with
Hermes's own interpreter: in a throwaway HERMES_HOME, one `coder` card and one `default` card,
plugins loaded as the gateway loads them, one dispatcher tick. The coder card must reach our
command (a stub that records its environment) with the run's grant; the default card must get
Hermes's own worker; the `hermes kanban` verbs the bridge calls must accept that grant; and
Hermes's exit contract must be what agent_runner/hermes_board.py says. Anything else fails
the build, so a Hermes update that moves the seam is caught when its PR builds.

Usage: contract.py <the plugin, as installed> <stub> <hermes> <hermes_board.py>
"""

import ast
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

installed, stub, hermes, board_source = sys.argv[1:5]
home = Path(os.environ["HERMES_HOME"])
recorded = home / "recorded.json"
# The plugin as installed, but its command's program is the stub and its home this one.
plugin = home / "plugins" / "card-worker"
plugin.mkdir(parents=True)
for name in ("__init__.py", "plugin.yaml"):
    shutil.copy(Path(installed) / name, plugin / name)
command = json.loads((Path(installed) / "command.json").read_text())
assert command[1:3] == ["-u", "PYTHONPATH"] and command[3].startswith(
    "HERMES_HOME="
), command
assert command[5] == "kanban-worker", command
(plugin / "command.json").write_text(
    json.dumps([*command[:3], f"HERMES_HOME={home}", stub])
)
(home / "profiles" / "coder").mkdir(parents=True)
(home / "profiles" / "coder" / ".env").write_text("")  # ./default.nix makes the same
(home / "config.yaml").write_text("plugins:\n  enabled: [card-worker]\n")


def kanban(*args: str, env: dict[str, str] | None = None) -> str:
    done = subprocess.run(
        [hermes, "kanban", *args], capture_output=True, text=True, env=env, check=False
    )
    assert done.returncode == 0, f"hermes kanban {args}: {done.stdout}{done.stderr}"
    return done.stdout


def create(title: str, assignee: str) -> str:
    out = json.loads(kanban("create", title, "--assignee", assignee, "--json"))
    return str(out["id"])


coder, default = create("a coding card", "coder"), create("a chat card", "default")

from hermes_cli import kanban_db as kb  # noqa: E402
from hermes_cli import kanban_db_connect as kbc  # noqa: E402
from hermes_cli import kanban_db_dispatch as kbd  # noqa: E402
from hermes_cli import quiet_single_query  # noqa: E402
from hermes_cli.plugins import discover_plugins  # noqa: E402

discover_plugins()

# Hermes's own worker isn't started (it would cold-start a gateway): its command is recorded.
hermes_workers: list[list[str]] = []
popen = subprocess.Popen


class NotStarted:
    pid = 2**22


def recording_popen(argv: list[str], **kw: object) -> object:
    if "hermes_cli.kanban_worker_client" in argv:
        hermes_workers.append(argv)
        return NotStarted()
    return popen(argv, **kw)  # type: ignore[call-overload]


subprocess.Popen = recording_popen  # type: ignore[assignment,misc]
with kbc.connect_closing() as conn:
    result = kbd.dispatch_once(conn)
subprocess.Popen = popen  # type: ignore[misc]
spawned = {task: who for task, who, _ in result.spawned}
assert spawned == {coder: "coder", default: "default"}, f"spawned: {result}"
assert len(hermes_workers) == 1, f"Hermes's own worker, not ours, for: {hermes_workers}"
assert hermes_workers[0][-2:] == [
    "-m",
    "hermes_cli.kanban_worker_client",
], hermes_workers

# The coder card reached our command, with the run's grant.
deadline = time.monotonic() + 30
while not recorded.exists() and time.monotonic() < deadline:
    time.sleep(0.1)
env = json.loads(recorded.read_text())
assert env["HERMES_KANBAN_TASK"] == coder, env
assert env["HERMES_HOME"] == str(
    home
), "the command resets HERMES_HOME to the board's home"
assert "PYTHONPATH" not in env, "the command drops Hermes's PYTHONPATH"
for key in ("HERMES_KANBAN_RUN_ID", "HERMES_KANBAN_CLAIM_LOCK", "HERMES_KANBAN_DB"):
    assert env.get(key), f"{key} missing: {env}"
assert Path(env["HERMES_KANBAN_WORKSPACE"]).is_dir(), env

# The verbs the bridge calls, with the grant, as it calls them.
assert "a coding card" in kanban("context", coder, env=env)
kanban("heartbeat", coder, "--note=MARKER", env=env)
kanban("comment", coder, "--", "a comment", env=env)
kanban("complete", coder, "--summary=contract done", env=env)
kanban("block", default, "--kind", "needs_input", "--", "a question")
with kbc.connect_closing() as conn:
    done, blocked = kb.get_task(conn, coder), kb.get_task(conn, default)
assert done is not None and done.status == "done", done
assert blocked is not None and blocked.status == "blocked", blocked
# No gateway would serve the coder profile: it has no config of its own.
assert sorted(p.name for p in (home / "profiles" / "coder").iterdir()) == [".env"]

# Hermes's exit contract, as hermes_board.py has it.
consts = {
    t.id: ast.literal_eval(node.value)
    for node in ast.parse(Path(board_source).read_text()).body
    if isinstance(node, ast.Assign)
    for t in node.targets
    if isinstance(t, ast.Name) and t.id in ("RATE_LIMITED", "EXIT_TRAILER")
}
assert consts["RATE_LIMITED"] == kb.KANBAN_RATE_LIMIT_EXIT_CODE
assert consts["EXIT_TRAILER"] == quiet_single_query.KANBAN_WORKER_EXIT_TRAILER
print("card-worker contract holds")
