"""What changes in a sliced plate between two profile versions: the G-code templates, the program
and the slicer's own estimates.

A sliced plate is the Bambu Studio CLI's 3MF (`Metadata/plate_1.gcode`). Its header holds the print
time and the filament used; its config block holds every setting, the G-code templates among them
(`; machine_start_gcode = ...`, with newlines written as `\\n`). The program is every other line,
compared without comments and without M73 (progress reports, which move with any time change).
"""

from __future__ import annotations

import re
import zipfile
from collections import Counter
from dataclasses import dataclass
from difflib import ndiff
from pathlib import Path

PLATE = "Metadata/plate_1.gcode"
# The machine's G-code templates: the settings a profile update changes the program through.
TEMPLATES = (
    "machine_start_gcode",
    "change_filament_gcode",
    "layer_change_gcode",
    "machine_end_gcode",
)
SETTING = re.compile(r"^; (\w+) = (.*)$", re.M)
TIME = re.compile(r"^; model printing time: .*; total estimated time: (.+)$", re.M)
WEIGHT = re.compile(r"^; total filament weight \[g\] : (.+)$", re.M)
# A move (G0 to G3): counted when it changes, not listed, as the template lines are.
MOVE = re.compile(r"^G[0-3](?:\s|$)")
# How many distinct changed program lines other than moves a case lists.
SHOWN_LINES = 8


@dataclass(frozen=True)
class Plate:
    """One sliced plate: its estimates, its templates and its program."""

    time: str
    grams: float
    templates: dict[str, list[str]]
    program: list[str]


@dataclass(frozen=True)
class PlateDiff:
    """Two slices of one case, ours (the pinned profiles) then theirs (the newer ones)."""

    time: tuple[str, str]
    grams: tuple[float, float]
    templates: dict[
        str, int
    ]  # template name: lines changed, for each template that changed
    removed: Counter[str]  # program lines only ours has, with how often
    added: Counter[str]  # program lines only theirs has, with how often


def parse(gcode: str) -> Plate:
    settings = dict(SETTING.findall(gcode))
    time = TIME.search(gcode)
    weight = WEIGHT.search(gcode)
    program = []
    for line in gcode.splitlines():
        code = line.split(";", 1)[0].strip()
        if code and not code.startswith("M73"):
            program.append(code)
    return Plate(
        time=time.group(1).strip() if time else "?",
        grams=sum(float(g) for g in weight.group(1).split(",")) if weight else 0.0,
        templates={k: settings.get(k, "").split("\\n") for k in TEMPLATES},
        program=program,
    )


def read(sliced: Path) -> Plate:
    with zipfile.ZipFile(sliced) as z:
        return parse(z.read(PLATE).decode())


def compare(ours: Plate, theirs: Plate) -> PlateDiff:
    templates = {}
    for k in TEMPLATES:
        changed = sum(
            1 for d in ndiff(ours.templates[k], theirs.templates[k]) if d[:1] in "+-"
        )
        if changed:
            templates[k] = changed
    a, b = Counter(ours.program), Counter(theirs.program)
    return PlateDiff(
        time=(ours.time, theirs.time),
        grams=(ours.grams, theirs.grams),
        templates=templates,
        removed=a - b,
        added=b - a,
    )


def render(name: str, about: str, d: PlateDiff) -> list[str]:
    """A few lines on one case, the same text for the same difference."""
    out = [f"{name} ({about}):"]
    out.append(
        f"  time {d.time[0]} -> {d.time[1]}, filament {d.grams[0]:.2f} g -> {d.grams[1]:.2f} g"
    )
    if d.templates:
        out.append(
            "  templates changed: "
            + ", ".join(f"{k} ({n} lines)" for k, n in d.templates.items())
        )
    else:
        out.append("  templates: no change")
    moves = sum(n for line, n in (d.removed + d.added).items() if MOVE.match(line))
    commands = sorted(
        [("-", line, n) for line, n in d.removed.items() if not MOVE.match(line)]
        + [("+", line, n) for line, n in d.added.items() if not MOVE.match(line)],
        key=lambda x: (-x[2], x[1], x[0]),
    )
    if not moves and not commands:
        out.append("  program: no change (comments and M73 aside)")
        return out
    out.append(
        f"  program (comments and M73 aside): {moves} move lines and "
        f"{sum(n for _, _, n in commands)} other lines differ"
    )
    out += [f"    {sign} {line}  (x{n})" for sign, line, n in commands[:SHOWN_LINES]]
    if len(commands) > SHOWN_LINES:
        out.append(f"    ... {len(commands) - SHOWN_LINES} more")
    return out
