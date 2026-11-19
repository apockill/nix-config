"""Tests for gcode.py."""

from __future__ import annotations

import zipfile
from pathlib import Path

import gcode

START_OURS = "M17\\nM620.17 T1 S{t} L{-1}\\nM400"
START_THEIRS = "M17\\nM620.17 T1 S{t} L{0}\\nM400"


def plate(start: str, start_line: str, time: str, grams: str) -> str:
    return "\n".join(
        [
            "; HEADER_BLOCK_START",
            f"; model printing time: 10m; total estimated time: {time}",
            f"; total filament weight [g] : {grams}",
            "; HEADER_BLOCK_END",
            f"; machine_start_gcode = {start}",
            "; layer_change_gcode = M991 S0",
            "M73 P0 R18",
            f"{start_line} ; for the unused nozzle",
            "G1 X10 Y10 F3000",
            "G1 X20 Y10 E0.5",
            "M73 P50 R9",
        ]
    )


def test_parse_reads_estimates_templates_and_the_program() -> None:
    p = gcode.parse(plate(START_OURS, "M620.17 T1 S220 L-1", "18m 31s", "1.00,0.92"))
    assert p.time == "18m 31s"
    assert p.grams == 1.92
    assert p.templates["machine_start_gcode"][1] == "M620.17 T1 S{t} L{-1}"
    # comments and M73 aside
    assert p.program == ["M620.17 T1 S220 L-1", "G1 X10 Y10 F3000", "G1 X20 Y10 E0.5"]


def test_compare_and_render_show_the_changed_lines() -> None:
    ours = gcode.parse(plate(START_OURS, "M620.17 T1 S220 L-1", "18m 31s", "1.92"))
    theirs = gcode.parse(plate(START_THEIRS, "M620.17 T1 S220 L0", "18m 40s", "1.95"))
    d = gcode.compare(ours, theirs)
    assert d.templates == {"machine_start_gcode": 2}
    text = "\n".join(gcode.render("towers", "one filament", d))
    assert "time 18m 31s -> 18m 40s, filament 1.92 g -> 1.95 g" in text
    assert "machine_start_gcode (2 lines)" in text
    assert "0 move lines and 2 other lines differ" in text
    assert "- M620.17 T1 S220 L-1  (x1)" in text
    assert "+ M620.17 T1 S220 L0  (x1)" in text


def test_moves_are_counted_not_listed() -> None:
    ours = gcode.parse(plate(START_OURS, "M400", "1m", "1"))
    theirs = gcode.parse(plate(START_OURS, "M400", "1m", "1").replace("F3000", "F3600"))
    text = "\n".join(gcode.render("c", "x", gcode.compare(ours, theirs)))
    assert "2 move lines and 0 other lines differ" in text
    assert "G1" not in text


def test_the_same_slices_render_no_change() -> None:
    p = gcode.parse(plate(START_OURS, "M400", "1m", "1"))
    text = gcode.render("c", "x", gcode.compare(p, p))
    assert text[-2:] == [
        "  templates: no change",
        "  program: no change (comments and M73 aside)",
    ]


def test_read_takes_the_plate_from_a_sliced_3mf(tmp_path: Path) -> None:
    sliced = tmp_path / "c.gcode.3mf"
    with zipfile.ZipFile(sliced, "w") as z:
        z.writestr(gcode.PLATE, plate(START_OURS, "M400", "5m", "2"))
    assert gcode.read(sliced).time == "5m"
