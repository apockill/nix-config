"""Tests for add_printer.py against a fake Bambuddy. Run with `just test`."""

from __future__ import annotations

import json
import threading
from collections.abc import Iterator
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

import add_printer
import pytest

SERIAL = "20P5AJ662701727"
CODE = "12345678"
ARGS = [
    "--name",
    "X2D",
    "--model",
    "X2D",
    "--ip",
    "192.168.86.54",
    "--serial",
    SERIAL,
    "--access-code-env",
    "TEST_ACCESS_CODE",
    "--wait",
    "5",
]


class FakeBambuddy:
    """Records the requests; answers from `printers` and `create_answer`."""

    def __init__(self) -> None:
        self.printers: list[dict[str, Any]] = []
        self.create_answer: tuple[int, Any] | None = None
        self.posts: list[dict[str, Any]] = []


@pytest.fixture
def bambuddy() -> Iterator[tuple[FakeBambuddy, str]]:
    fake = FakeBambuddy()

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_: Any) -> None:
            pass

        def answer(self, status: int, body: Any) -> None:
            data = json.dumps(body).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self) -> None:
            if self.path == "/health":
                self.answer(200, {"status": "healthy"})
            elif self.path == "/api/v1/printers/":
                self.answer(200, fake.printers)
            else:
                self.answer(404, {"detail": "Not Found"})

        def do_POST(self) -> None:
            body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            fake.posts.append(body)
            if fake.create_answer is not None:
                self.answer(*fake.create_answer)
                return
            created = {"id": len(fake.printers) + 1, **body}
            del created["access_code"]
            fake.printers.append(created)
            self.answer(200, created)

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield fake, f"http://127.0.0.1:{server.server_address[1]}"
    server.shutdown()


@pytest.fixture(autouse=True)
def access_code(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TEST_ACCESS_CODE", CODE)


def test_adds_a_missing_printer(bambuddy: tuple[FakeBambuddy, str]) -> None:
    fake, url = bambuddy
    assert add_printer.main(["--url", url, *ARGS]) == add_printer.EXIT_OK
    assert fake.posts == [
        {
            "name": "X2D",
            "model": "X2D",
            "ip_address": "192.168.86.54",
            "serial_number": SERIAL,
            "access_code": CODE,
        }
    ]


def test_second_run_changes_nothing(bambuddy: tuple[FakeBambuddy, str]) -> None:
    fake, url = bambuddy
    assert add_printer.main(["--url", url, *ARGS]) == add_printer.EXIT_OK
    assert add_printer.main(["--url", url + "/", *ARGS]) == add_printer.EXIT_OK
    assert len(fake.posts) == 1
    assert len(fake.printers) == 1


def test_serial_matches_in_any_case(bambuddy: tuple[FakeBambuddy, str]) -> None:
    fake, url = bambuddy
    fake.printers = [{"id": 7, "name": "Renamed", "serial_number": SERIAL.lower()}]
    assert add_printer.main(["--url", url, *ARGS]) == add_printer.EXIT_OK
    assert fake.posts == []


def test_other_printers_dont_count(bambuddy: tuple[FakeBambuddy, str]) -> None:
    fake, url = bambuddy
    fake.printers = [{"id": 1, "name": "A1", "serial_number": "0309DA000000000"}]
    assert add_printer.main(["--url", url, *ARGS]) == add_printer.EXIT_OK
    assert len(fake.posts) == 1


def test_unreachable_printer_asks_for_a_retry(
    bambuddy: tuple[FakeBambuddy, str], capsys: pytest.CaptureFixture[str]
) -> None:
    fake, url = bambuddy
    fake.create_answer = (
        400,
        {
            "detail": {
                "code": "printer_connection_failed",
                "message": "Could not connect",
            }
        },
    )
    assert add_printer.main(["--url", url, *ARGS]) == add_printer.EXIT_UNREACHABLE
    assert "will retry" in capsys.readouterr().err


def test_refusal_never_prints_the_access_code(
    bambuddy: tuple[FakeBambuddy, str], capsys: pytest.CaptureFixture[str]
) -> None:
    fake, url = bambuddy
    # FastAPI's 422 echoes the offending input.
    fake.create_answer = (
        422,
        {"detail": [{"loc": ["body"], "input": {"access_code": CODE}}]},
    )
    assert add_printer.main(["--url", url, *ARGS]) == add_printer.EXIT_REFUSED
    out = capsys.readouterr()
    assert CODE not in out.err + out.out
    assert "<access code>" in out.err


def test_missing_access_code_fails_before_any_request(
    bambuddy: tuple[FakeBambuddy, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    fake, url = bambuddy
    monkeypatch.delenv("TEST_ACCESS_CODE")
    assert add_printer.main(["--url", url, *ARGS]) == add_printer.EXIT_REFUSED
    assert fake.posts == []


def test_bambuddy_down(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(add_printer, "POLL_SECONDS", 0.05)
    args = [*ARGS[:-1], "0.2"]
    assert (
        add_printer.main(["--url", "http://127.0.0.1:9", *args])
        == add_printer.EXIT_NO_BAMBUDDY
    )
