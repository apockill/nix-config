"""Shared test fixtures: a stand-in orca-slicer-api and a free port."""

from __future__ import annotations

import socket
import sys
from pathlib import Path

import pytest

# A stand-in for orca-slicer-api: serves /health and POST /slice on $PORT, keeps each request body
# in $DATA_PATH, and answers with a sliced 3MF whose start line depends on the profiles' version
# (L-1 for 02.08.00.01, as the bundled profiles have it, L0 otherwise).
FAKE_SERVER = """
import io, json, os, zipfile
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

PROFILES = Path(os.environ["BUNDLED_PROFILES_PATH"])
DATA = Path(os.environ["DATA_PATH"])

class H(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200 if self.path == "/health" else 404)
        self.end_headers()

    def do_POST(self):
        body = self.rfile.read(int(self.headers["Content-Length"]))
        n = len(list(DATA.glob("request-*")))
        (DATA / f"request-{n}").write_bytes(body)
        version = json.loads((PROFILES.parent / "BBL.json").read_text())["version"]
        last = "-1" if version == "02.08.00.01" else "0"
        gcode = "\\n".join([
            "; model printing time: 1m; total estimated time: 2m",
            "; total filament weight [g] : 1.5",
            f"; machine_start_gcode = M17\\\\nM620.17 L{last}",
            "M17",
            f"M620.17 T1 S220 L{last}",
        ])
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as z:
            z.writestr("Metadata/plate_1.gcode", gcode)
        self.send_response(200)
        self.end_headers()
        self.wfile.write(buf.getvalue())

    def log_message(self, *args):
        pass

HTTPServer(("127.0.0.1", int(os.environ["PORT"])), H).serve_forever()
"""


@pytest.fixture
def fake_orca_slicer_api(tmp_path: Path) -> Path:
    script = tmp_path / "fake-orca-slicer-api"
    script.write_text(f"#!{sys.executable}\n{FAKE_SERVER}")
    script.chmod(0o755)
    return script


@pytest.fixture
def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port: int = s.getsockname()[1]
        return port


def profiles_tree(root: Path, version: str) -> Path:
    """A minimal profiles dir: BBL.json of `version` and an empty BBL/."""
    (root / "BBL").mkdir(parents=True)
    (root / "BBL.json").write_text(f'{{"name": "BBL", "version": "{version}"}}')
    return root
