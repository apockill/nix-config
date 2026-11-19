"""Slicing a case as our stack does, through a private orca-slicer-api on its own port.

lab-printer asks Bambuddy for a slice with stock presets by name and its own process overrides;
Bambuddy posts orca-slicer-api's POST /slice a stub per preset (`{name, inherits: name, from:
system, type}`, its preset_resolver._resolve_standard), the colours written into the filament
stubs, the overrides and the build plate (`curr_bed_type`) written into the process stub, and the
filament map. orca-slicer-api resolves each stub from BUNDLED_PROFILES_PATH and runs the CLI. This
sends the same form to an orca-slicer-api started with the profile tree under test, so two slices
of a case differ only in the profiles.
"""

from __future__ import annotations

import json
import os
import subprocess
import time
import urllib.request
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

import requests  # type: ignore[import-untyped]  # lint's mypy has no types-requests

# The server starts in a second or two.
START_TIMEOUT_S = 60
# The slowest case slices in about two minutes under load; ten means stuck.
SLICE_TIMEOUT_S = 10 * 60
# A setting's value as a preset stores it: one string, or one per entry.
type Value = str | list[str]
type ProfileType = Literal["machine", "process", "filament"]


class SliceError(Exception):
    pass


@dataclass(frozen=True)
class Filament:
    preset: str
    colour: str


@dataclass(frozen=True)
class Case:
    """One slice request, as lab-printer's goes out through Bambuddy (cases.json)."""

    name: str
    about: str
    model: str
    printer: str
    process: str
    filaments: list[Filament]
    filament_map: list[int]
    process_overrides: dict[str, Value]


@dataclass(frozen=True)
class Tools:
    orca_slicer_api: Path
    bambu_studio: Path


def load_cases(path: Path) -> list[Case]:
    raw = json.loads(path.read_text())
    return [
        Case(
            name=c["name"],
            about=c["about"],
            model=c["model"],
            printer=c["printer"],
            process=c["process"],
            filaments=[Filament(f["preset"], f["colour"]) for f in c["filaments"]],
            filament_map=[int(e) for e in c["filament_map"]],
            process_overrides=c["process_overrides"],
        )
        for c in raw["cases"]
    ]


def stub(name: str, kind: ProfileType, **settings: Value) -> bytes:
    """A stock preset by name, as Bambuddy sends it, with settings written on top."""
    return json.dumps(
        {"name": name, "inherits": name, "from": "system", "type": kind, **settings}
    ).encode()


def form(
    case: Case, model: bytes
) -> tuple[list[tuple[str, tuple[str, bytes, str]]], dict[str, str]]:
    """The multipart files and fields of POST /slice for `case`."""
    files = [
        ("file", (case.model, model, "model/3mf")),
        (
            "printerProfile",
            ("printer.json", stub(case.printer, "machine"), "application/json"),
        ),
        (
            "presetProfile",
            (
                "preset.json",
                stub(case.process, "process", **case.process_overrides),
                "application/json",
            ),
        ),
    ]
    for i, f in enumerate(case.filaments, 1):
        body = stub(f.preset, "filament", filament_colour=[f.colour])
        files.append(
            ("filamentProfile", (f"filament_{i}.json", body, "application/json"))
        )
    fields = {
        "exportType": "3mf",
        "filamentMap": ",".join(str(e) for e in case.filament_map),
    }
    return files, fields


@contextmanager
def private_slicer(
    tools: Tools, profiles: Path, port: int, work: Path
) -> Iterator[str]:
    """orca-slicer-api on 127.0.0.1:`port` slicing with `profiles` (a tree holding BBL/); its
    base URL. `work` holds its data, HOME and temporary files; no part of its path may start
    with a dot, or the server refuses to send the result back (Express's dotfiles rule).
    """
    for d in ("data", "home", "tmp"):
        (work / d).mkdir(parents=True, exist_ok=True)
    env = {
        **os.environ,
        "HOST": "127.0.0.1",
        "PORT": str(port),
        "ORCASLICER_PATH": str(tools.bambu_studio),
        "BUNDLED_PROFILES_PATH": str(profiles / "BBL"),
        "DATA_PATH": str(work / "data"),
        "HOME": str(work / "home"),
        "TMPDIR": str(work / "tmp"),
    }
    log = (work / "orca-slicer-api.log").open("w")
    server = subprocess.Popen(
        [str(tools.orca_slicer_api)], env=env, stdout=log, stderr=subprocess.STDOUT
    )
    base = f"http://127.0.0.1:{port}"
    try:
        deadline = time.monotonic() + START_TIMEOUT_S
        while True:
            if server.poll() is not None:
                raise SliceError(
                    f"orca-slicer-api exited ({server.returncode}); see {log.name}"
                )
            try:
                with urllib.request.urlopen(f"{base}/health", timeout=5):
                    break
            except OSError:
                if time.monotonic() > deadline:
                    raise SliceError(
                        f"orca-slicer-api didn't start on port {port}"
                    ) from None
                time.sleep(0.5)
        yield base
    finally:
        server.terminate()
        try:
            server.wait(timeout=30)
        except subprocess.TimeoutExpired:
            server.kill()
            server.wait()
        log.close()


def slice_case(base: str, case: Case, models: Path) -> bytes:
    """The sliced plate (a 3MF holding Metadata/plate_1.gcode)."""
    files, fields = form(case, (models / case.model).read_bytes())
    try:
        r = requests.post(
            f"{base}/slice", files=files, data=fields, timeout=SLICE_TIMEOUT_S
        )
    except requests.RequestException as e:
        raise SliceError(f"{case.name}: {e}") from e
    if r.status_code != 200:
        raise SliceError(f"{case.name}: HTTP {r.status_code}: {r.text[:300]}")
    return r.content
