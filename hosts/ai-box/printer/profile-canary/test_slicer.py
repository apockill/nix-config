"""Tests for slicer.py, against a stand-in orca-slicer-api (conftest.py)."""

from __future__ import annotations

import json
import zipfile
from pathlib import Path

import pytest
import slicer
from conftest import profiles_tree

HERE = Path(__file__).parent


def test_the_vendored_cases_load_and_have_their_models() -> None:
    cases = slicer.load_cases(HERE / "cases.json")
    assert [c.name for c in cases] == ["towers-right-plabasic", "pair-petg-left"]
    for c in cases:
        assert (HERE / "models" / c.model).is_file()
        assert len(c.filament_map) == len(c.filaments)


def test_the_form_is_bambuddys() -> None:
    case = slicer.load_cases(HERE / "cases.json")[1]
    files, fields = slicer.form(case, b"model")
    names = [f[0] for f in files]
    assert names == [
        "file",
        "printerProfile",
        "presetProfile",
        "filamentProfile",
        "filamentProfile",
    ]
    process = json.loads(files[2][1][1])
    assert process["inherits"] == process["name"] == "0.20mm Standard @BBL X2D"
    assert process["from"] == "system" and process["type"] == "process"
    assert process["wipe_tower_y"] == ["206.096"]
    assert json.loads(files[4][1][1])["filament_colour"] == ["#FFFFFF"]
    assert fields == {"exportType": "3mf", "filamentMap": "1,1"}


def test_slices_through_a_private_server(
    tmp_path: Path, fake_orca_slicer_api: Path, free_port: int
) -> None:
    tools = slicer.Tools(fake_orca_slicer_api, tmp_path / "bambu-studio")
    tree = profiles_tree(tmp_path / "tree", "02.08.00.06")
    case = slicer.load_cases(HERE / "cases.json")[0]
    work = tmp_path / "work"
    with slicer.private_slicer(tools, tree, free_port, work) as base:
        sliced = slicer.slice_case(base, case, HERE / "models")
    out = tmp_path / "c.gcode.3mf"
    out.write_bytes(sliced)
    with zipfile.ZipFile(out) as z:
        assert "L0" in z.read("Metadata/plate_1.gcode").decode()
    body = (work / "data" / "request-0").read_bytes()
    assert b'name="printerProfile"' in body and b'"enable_prime_tower": ["0"]' in body


def test_a_server_that_dies_is_a_slice_error(tmp_path: Path, free_port: int) -> None:
    dead = tmp_path / "dead"
    dead.write_text("#!/bin/sh\nexit 3\n")
    dead.chmod(0o755)
    tools = slicer.Tools(dead, tmp_path)
    with pytest.raises(slicer.SliceError, match="exited"):
        with slicer.private_slicer(tools, tmp_path, free_port, tmp_path / "work"):
            pass
