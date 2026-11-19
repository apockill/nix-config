"""Report what Bambu's newer BBL profiles would change in our slices; never switch to them.

1. Ask Bambu's update endpoint which profile package it offers our Bambu Studio, as the app does
   (endpoint.py). If the app wouldn't install it over the profiles the slicer service pins (it
   isn't newer, or not of the app's major.minor), say so and stop.
2. Once per offered version (and pinned version): download the package into the state dir,
   pre-merge it as the slicer service's tree is (package.py), slice each case of cases.json with
   both trees through a private orca-slicer-api (slicer.py), and keep the difference
   (gcode.py) as report-vs-<pinned>.txt beside the package.
3. Write summary.txt: a few lines, the same while nothing changes, for the cron monitor.

usage: canary.py --state DIR --pinned-tree DIR --app-version V --cases FILE --models DIR
                 --orca-slicer-api BIN --bambu-studio BIN --premerge FILE --defaults FILE
                 --preset-cpp FILE --print-config-cpp FILE [--port N] [--endpoint URL]
"""

from __future__ import annotations

import argparse
import tempfile
from dataclasses import dataclass
from pathlib import Path

import endpoint
import gcode
import package
import slicer

SUMMARY = "summary.txt"


@dataclass(frozen=True)
class Config:
    state: Path
    pinned_tree: Path
    app: endpoint.Version
    cases: Path
    models: Path
    tools: slicer.Tools
    premerge: package.Premerge
    port: int
    endpoint: str


def compare(cfg: Config, theirs_tree: Path, work: Path) -> list[str]:
    """Each case sliced with the pinned tree and with `theirs_tree`, and how they differ."""
    cases = slicer.load_cases(cfg.cases)
    plates: dict[str, list[gcode.Plate]] = {c.name: [] for c in cases}
    for side, tree in (("ours", cfg.pinned_tree), ("theirs", theirs_tree)):
        with slicer.private_slicer(cfg.tools, tree, cfg.port, work / side) as base:
            for c in cases:
                out = work / side / f"{c.name}.gcode.3mf"
                out.write_bytes(slicer.slice_case(base, c, cfg.models))
                plates[c.name].append(gcode.read(out))
    lines: list[str] = []
    for c in cases:
        ours, theirs = plates[c.name]
        lines += gcode.render(c.name, c.about, gcode.compare(ours, theirs))
    return lines


def report(cfg: Config, offer: endpoint.Offer, pinned: endpoint.Version) -> list[str]:
    """The comparison for this offer and pin, made once and kept in the state dir."""
    kept = cfg.state / str(offer.version)
    done = kept / f"report-vs-{pinned}.txt"
    if done.is_file():
        return done.read_text().splitlines()
    kept.mkdir(parents=True, exist_ok=True)
    zip_path = kept / "package.zip"
    if not zip_path.is_file():
        partial = kept / "package.zip.part"
        package.download(offer.url, partial)
        partial.rename(zip_path)
    with tempfile.TemporaryDirectory(prefix="bambu-profile-canary-") as tmp:
        work = Path(tmp)
        raw = package.unpack(zip_path, work / "package")
        merged = package.premerge(
            raw, str(offer.version), cfg.premerge, work / "premerged"
        )
        lines = compare(cfg, merged, work)
    done.write_text("\n".join(lines) + "\n")
    return lines


def summary(cfg: Config) -> list[str]:
    pinned = endpoint.Version.parse(package.version_of(cfg.pinned_tree))
    offer = endpoint.ask(cfg.app, cfg.endpoint)
    if offer is None:
        return [
            f"OK: Bambu offers Bambu Studio {cfg.app} no BBL profile package; ours: {pinned}."
        ]
    if not endpoint.installs(cfg.app, pinned, offer.version):
        return [
            f"OK: Bambu offers Bambu Studio {cfg.app} BBL profiles {offer.version}; "
            f"the slicer service pins {pinned}: nothing newer."
        ]
    return [
        f"NEW: Bambu offers Bambu Studio {cfg.app} BBL profiles {offer.version}, newer than the "
        f"{pinned} the slicer service pins. Nothing was switched; slices of the same requests "
        f"with each:",
        *report(cfg, offer, pinned),
    ]


def write_summary(state: Path, lines: list[str]) -> None:
    tmp = state / f"{SUMMARY}.tmp"
    tmp.write_text("\n".join(lines) + "\n")
    tmp.replace(state / SUMMARY)


def parse_args(argv: list[str] | None) -> Config:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument(
        "--state", type=Path, required=True, help="kept packages and reports"
    )
    ap.add_argument(
        "--pinned-tree", type=Path, required=True, help="the slicer service's tree"
    )
    ap.add_argument(
        "--app-version", required=True, help="the slicer's Bambu Studio version"
    )
    ap.add_argument("--cases", type=Path, required=True)
    ap.add_argument("--models", type=Path, required=True)
    ap.add_argument("--orca-slicer-api", type=Path, required=True)
    ap.add_argument("--bambu-studio", type=Path, required=True)
    ap.add_argument(
        "--premerge", type=Path, required=True, help="the service's premerge.py"
    )
    ap.add_argument("--defaults", type=Path, required=True)
    ap.add_argument("--preset-cpp", type=Path, required=True)
    ap.add_argument("--print-config-cpp", type=Path, required=True)
    ap.add_argument(
        "--port", type=int, default=3002, help="the private orca-slicer-api's"
    )
    ap.add_argument("--endpoint", default=endpoint.URL)
    a = ap.parse_args(argv)
    return Config(
        state=a.state,
        pinned_tree=a.pinned_tree,
        app=endpoint.Version.parse(a.app_version),
        cases=a.cases,
        models=a.models,
        tools=slicer.Tools(a.orca_slicer_api, a.bambu_studio),
        premerge=package.Premerge(
            a.premerge, a.defaults, a.preset_cpp, a.print_config_cpp
        ),
        port=a.port,
        endpoint=a.endpoint,
    )


def main(argv: list[str] | None = None) -> int:
    cfg = parse_args(argv)
    cfg.state.mkdir(parents=True, exist_ok=True)
    try:
        lines = summary(cfg)
    except (endpoint.EndpointError, package.PackageError, slicer.SliceError) as e:
        write_summary(cfg.state, [f"PROBLEM: {e}"])
        print(f"PROBLEM: {e}")
        return 1
    write_summary(cfg.state, lines)
    print("\n".join(lines))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
