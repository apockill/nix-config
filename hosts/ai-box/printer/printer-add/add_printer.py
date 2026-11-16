"""Adds a printer to Bambuddy unless one with its serial number is already there.

Run by bambuddy-add-printer.service (./default.nix) after Bambuddy starts. It waits for
Bambuddy's /health, lists its printers, and creates the printer through
`POST /api/v1/printers/` only when no printer has the same serial. Bambuddy logs into the
printer's MQTT before it saves a new printer, so an unreachable printer (switched off, a
wrong access code) fails the run, and systemd retries it later.

The access code is read from an environment variable named by --access-code-env (systemd
loads it from the agent's secrets file) and is never printed.

Exit codes: 0 added or already there, 1 Bambuddy refused or failed, 2 the printer didn't
answer Bambuddy's connection test, 3 Bambuddy never came up.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any

# How long to wait for Bambuddy's /health after it starts: it migrates its database and
# loads its services first, which takes a few seconds on ai-box.
DEFAULT_WAIT_SECONDS = 120.0  # 2 minutes
# Pause between /health tries while waiting.
POLL_SECONDS = 2.0
# Per request. Creating a printer includes Bambuddy's MQTT login to it (about 5 s).
REQUEST_TIMEOUT_SECONDS = 60.0
EXIT_OK = 0
EXIT_REFUSED = 1
EXIT_UNREACHABLE = 2
EXIT_NO_BAMBUDDY = 3


@dataclass(frozen=True)
class Printer:
    """The printer to declare, in the fields of Bambuddy's `PrinterCreate`."""

    name: str
    model: str
    ip_address: str
    serial_number: str
    access_code: str

    def create_body(self) -> dict[str, str]:
        return {
            "name": self.name,
            "model": self.model,
            "ip_address": self.ip_address,
            "serial_number": self.serial_number,
            "access_code": self.access_code,
        }


class BambuddyError(Exception):
    """Bambuddy answered with an error status."""

    def __init__(self, status: int, body: str) -> None:
        super().__init__(f"HTTP {status}: {body}")
        self.status = status
        self.body = body


def request(url: str, body: dict[str, str] | None = None) -> Any:
    """GET `url`, or POST `body` as JSON to it; returns the decoded JSON answer."""
    data = None if body is None else json.dumps(body).encode()
    req = urllib.request.Request(url, data=data)
    if data is not None:
        req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=REQUEST_TIMEOUT_SECONDS) as response:
            return json.loads(response.read() or b"null")
    except urllib.error.HTTPError as error:
        raise BambuddyError(error.code, error.read().decode(errors="replace")) from None


def wait_for_health(base_url: str, wait_seconds: float) -> bool:
    """True once Bambuddy's /health answers, False if it doesn't within `wait_seconds`."""
    deadline = time.monotonic() + wait_seconds
    while True:
        try:
            request(f"{base_url}/health")
            return True
        except (OSError, BambuddyError):
            if time.monotonic() >= deadline:
                return False
            time.sleep(POLL_SECONDS)


def find_by_serial(
    printers: list[dict[str, Any]], serial: str
) -> dict[str, Any] | None:
    """The listed printer with `serial`, compared as Bambuddy stores it (uppercase)."""
    for printer in printers:
        if (
            str(printer.get("serial_number", "")).strip().upper()
            == serial.strip().upper()
        ):
            return printer
    return None


def is_connection_failure(error: BambuddyError) -> bool:
    """Whether Bambuddy refused the printer because its MQTT connection test failed."""
    try:
        detail = json.loads(error.body).get("detail")
    except (ValueError, AttributeError):
        return False
    return (
        isinstance(detail, dict) and detail.get("code") == "printer_connection_failed"
    )


def add_printer(base_url: str, printer: Printer) -> int:
    """Create `printer` in Bambuddy unless it's there; returns the exit code."""
    api = f"{base_url}/api/v1/printers/"
    existing = find_by_serial(request(api), printer.serial_number)
    if existing is not None:
        print(
            f"{printer.serial_number}: already in Bambuddy as id {existing.get('id')}"
        )
        return EXIT_OK
    try:
        created = request(api, printer.create_body())
    except BambuddyError as error:
        if is_connection_failure(error):
            print(
                f"{printer.serial_number}: Bambuddy couldn't connect to the printer at "
                f"{printer.ip_address}; will retry",
                file=sys.stderr,
            )
            return EXIT_UNREACHABLE
        # FastAPI's validation errors echo the request body, access code included.
        reason = str(error).replace(printer.access_code, "<access code>")
        print(
            f"{printer.serial_number}: Bambuddy refused it: {reason}", file=sys.stderr
        )
        return EXIT_REFUSED
    print(f"{printer.serial_number}: added to Bambuddy as id {created.get('id')}")
    return EXIT_OK


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--url", required=True, help="Bambuddy's base URL")
    parser.add_argument("--name", required=True)
    parser.add_argument("--model", required=True)
    parser.add_argument("--ip", required=True)
    parser.add_argument("--serial", required=True)
    parser.add_argument(
        "--access-code-env",
        required=True,
        help="name of the environment variable holding the printer's access code",
    )
    parser.add_argument("--wait", type=float, default=DEFAULT_WAIT_SECONDS)
    return parser.parse_args(argv)


def main(argv: list[str]) -> int:
    args = parse_args(argv)
    access_code = os.environ.get(args.access_code_env, "")
    if not access_code:
        print(f"{args.access_code_env} is not set", file=sys.stderr)
        return EXIT_REFUSED
    base_url = args.url.rstrip("/")
    if not wait_for_health(base_url, args.wait):
        print(
            f"Bambuddy at {base_url} didn't come up in {args.wait:.0f} s",
            file=sys.stderr,
        )
        return EXIT_NO_BAMBUDDY
    printer = Printer(args.name, args.model, args.ip, args.serial, access_code)
    try:
        return add_printer(base_url, printer)
    except (OSError, BambuddyError) as error:
        print(f"Bambuddy request failed: {error}", file=sys.stderr)
        return EXIT_REFUSED


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
