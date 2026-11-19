"""Tests for canary.py, end to end: a stand-in endpoint, a package on disk (file://) and a
stand-in orca-slicer-api (conftest.py)."""

from __future__ import annotations

import json
import threading
import zipfile
from collections.abc import Iterator
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import canary
import pytest
from conftest import profiles_tree

HERE = Path(__file__).parent
# A premerge.py stand-in: copies the raw package to --out.
PREMERGE = (
    "import shutil, sys\n"
    "a = sys.argv[1:]\n"
    "shutil.copytree(a[a.index('--profiles') + 1], a[a.index('--out') + 1])\n"
)


@pytest.fixture
def endpoint_answer() -> Iterator[dict[str, object]]:
    """A stand-in update endpoint answering with whatever the test puts in the dict's "body"."""
    answer: dict[str, object] = {}

    class H(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            answer["query"] = self.path
            self.send_response(200)
            self.end_headers()
            self.wfile.write(str(answer["body"]).encode())

        def log_message(self, *args: object) -> None:
            pass

    server = HTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    answer["url"] = f"http://127.0.0.1:{server.server_port}/resource"
    yield answer
    server.shutdown()


def offering(answer: dict[str, object], version: str, url: str) -> None:
    resource = {"type": "slicer/settings/bbl", "version": version, "url": url}
    answer["body"] = json.dumps({"message": "success", "resources": [resource]})


def args(
    tmp_path: Path, answer: dict[str, object], orca: Path, port: int, pinned: Path
) -> list[str]:
    (tmp_path / "premerge.py").write_text(PREMERGE)
    return [
        "--state", str(tmp_path / "state"),
        "--pinned-tree", str(pinned),
        "--app-version", "02.08.00.50",
        "--cases", str(HERE / "cases.json"),
        "--models", str(HERE / "models"),
        "--orca-slicer-api", str(orca),
        "--bambu-studio", str(tmp_path / "bambu-studio"),
        "--premerge", str(tmp_path / "premerge.py"),
        "--defaults", str(tmp_path / "defaults.json"),
        "--preset-cpp", str(tmp_path / "Preset.cpp"),
        "--print-config-cpp", str(tmp_path / "PrintConfig.cpp"),
        "--port", str(port),
        "--endpoint", str(answer["url"]),
    ]  # fmt: skip


def package_zip(path: Path, version: str) -> Path:
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("BBL.json", json.dumps({"name": "BBL", "version": version}))
        z.writestr("BBL/machine/x.json", "{}")
    return path


def summary(tmp_path: Path) -> str:
    return (tmp_path / "state" / "summary.txt").read_text()


def test_nothing_newer(
    tmp_path: Path,
    endpoint_answer: dict[str, object],
    fake_orca_slicer_api: Path,
    free_port: int,
) -> None:
    offering(endpoint_answer, "02.08.00.06", "file:///nowhere.zip")
    pinned = profiles_tree(tmp_path / "pinned", "02.08.00.06")
    assert (
        canary.main(
            args(tmp_path, endpoint_answer, fake_orca_slicer_api, free_port, pinned)
        )
        == 0
    )
    assert endpoint_answer["query"] == "/resource?slicer/settings/bbl=02.08.00.00"
    assert summary(tmp_path) == (
        "OK: Bambu offers Bambu Studio 02.08.00.50 BBL profiles 02.08.00.06; "
        "the slicer service pins 02.08.00.06: nothing newer.\n"
    )


def test_a_newer_package_is_sliced_and_reported_once(
    tmp_path: Path,
    endpoint_answer: dict[str, object],
    fake_orca_slicer_api: Path,
    free_port: int,
) -> None:
    pkg = package_zip(tmp_path / "02.08.00.06.zip", "02.08.00.06")
    offering(endpoint_answer, "02.08.00.06", pkg.as_uri())
    pinned = profiles_tree(tmp_path / "pinned", "02.08.00.01")
    argv = args(tmp_path, endpoint_answer, fake_orca_slicer_api, free_port, pinned)
    assert canary.main(argv) == 0
    text = summary(tmp_path)
    assert text.startswith(
        "NEW: Bambu offers Bambu Studio 02.08.00.50 BBL profiles 02.08.00.06"
    )
    assert (
        "towers-right-plabasic (one filament, Bambu PLA Basic on the right nozzle):"
        in text
    )
    assert (
        "- M620.17 T1 S220 L-1  (x1)" in text and "+ M620.17 T1 S220 L0  (x1)" in text
    )
    assert "machine_start_gcode (2 lines)" in text
    kept = tmp_path / "state" / "02.08.00.06"
    assert (kept / "package.zip").is_file()
    assert (kept / "report-vs-02.08.00.01.txt").is_file()
    # once per version: the next run reuses the report (the package is gone, and nothing slices)
    pkg.unlink()
    (kept / "package.zip").unlink()
    assert canary.main(argv) == 0
    assert summary(tmp_path) == text


def test_a_failure_is_a_stable_problem_line(
    tmp_path: Path,
    endpoint_answer: dict[str, object],
    fake_orca_slicer_api: Path,
    free_port: int,
) -> None:
    endpoint_answer["body"] = json.dumps({"message": "fail"})
    pinned = profiles_tree(tmp_path / "pinned", "02.08.00.06")
    assert (
        canary.main(
            args(tmp_path, endpoint_answer, fake_orca_slicer_api, free_port, pinned)
        )
        == 1
    )
    assert summary(tmp_path).startswith("PROBLEM: the endpoint didn't answer success")
