"""Cron monitor source for desklab's calibration pipeline (see desklab-calibration.nix).

Prints a stable summary of what needs a decision. Hermes runs the cron model only
when this output changes, so it must not contain timestamps or anything else that
changes on its own. The contract is desklab's /api/calibrate/watch
(contract desklab.calibration/1).
"""

import http.client
import json
import socket
from typing import Any

SOCK = "/var/lib/hermes/sites/desklab/app.sock"


class UnixHTTPConnection(http.client.HTTPConnection):
    def __init__(self, path: str) -> None:
        super().__init__("localhost", timeout=10)
        self.path = path

    def connect(self) -> None:
        self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.sock.settimeout(10)
        self.sock.connect(self.path)


def get(path: str) -> dict[str, Any]:
    c = UnixHTTPConnection(SOCK)
    c.request("GET", path)
    r = c.getresponse()
    body = r.read()
    if r.status != 200:
        raise OSError(f"HTTP {r.status}")
    return json.loads(body)


try:
    w = get("/api/calibrate/watch")
except (OSError, ValueError):
    # desklab restarts often; being down isn't a calibration decision.
    print("OK: no calibration decision pending (desklab not reachable)")
    raise SystemExit(0) from None

if w.get("needs_attention"):
    att: dict[str, Any] = {}
    try:
        att = get("/api/calibrate/status").get("attention") or {}
    except (OSError, ValueError):
        pass
    print(
        f"NEEDS ATTENTION: bundle {w.get('bundle')}, stage {w.get('stage')}, id {w.get('attention_id')}"
    )
    print(f"question: {att.get('question') or w.get('message')}")
    print(
        f"answers: {', '.join(att.get('options') or ['continue', 'retry', 'skip', 'abort', 'ask_alex'])}"
    )
elif w.get("needs_alex"):
    print(
        f"NEEDS ALEX: bundle {w.get('bundle')}, state {w.get('state')}: {w.get('message')}"
    )
else:
    print("OK: no calibration decision pending")
