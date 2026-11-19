"""Bambu Studio's BBL profiles with each filament preset's `include` templates merged in.

Bambu Studio's app loads a vendor preset as: its parent's resolved config, then each template
its `include` list names, then the preset's own keys (PresetBundle::load_vendor_configs_from_json,
src/libslic3r/PresetBundle.cpp). orca-slicer-api's resolver walks `inherits` only, so a preset
handed to the CLI lost its template: on the X2D, `filament_extruder_variant` and every per-variant
value written for it, and a right (Bowden) nozzle filament sliced with Direct Drive retraction.

This writes a copy of the BBL tree in which every filament preset with an `include` carries the
template's settings in its own file, below its own keys. The resolver's unchanged `inherits` walk
then puts the parent below that, which is the app's order. Every file in the chain is merged, so
a parent's include also lands at the parent's level.

The app applies only the template keys that differ from the filament collection's default preset:
`include_config.diff(*include_default_config)`, then `config.apply_only(include_config, keys)`.
A template key equal to the default leaves the parent's value. That default preset is
(PresetBundle::PresetBundle, Preset.cpp's PresetCollection constructor):
  - FullPrintConfig's defaults, restricted to Preset::filament_options() (s_Preset_filament_options
    in Preset.cpp); a template key outside that list is never applied;
  - every filament extruder override key (filament_extruder_override_keys in PrintConfig.cpp, plus
    filament_retract_length_nc; all nullable) set to "nil";
  - filament_settings_id set to [""].
The FullPrintConfig defaults come from the shipped binary itself (`bambu-studio --export-settings`
with no inputs), not from parsing C++ initialisers; the two key lists are plain string lists in the
same version's source. Comparison follows ConfigOption::operator==: a vector differs from one of
another length, nil equals nil, and numbers compare by value.

Machine presets also use `include`, for their G-code companions (`<preset> template
machine_start_gcode` and so on); the resolver already applies those by name, so they're copied as
they are. Process presets have no includes.

The app also starts every filament preset from that default preset, so a key no file in a chain
sets is the default. The CLI starts from nothing: it copies into the slice only the keys each
filament's file holds (BambuStudio.cpp, `for (opt_key : config.keys())`), and `set_at` pads a list
with its first value (Config.hpp). So a key only some filaments' chains set (pre_start_fan_time:
Bambu PLA Pure's 2 s) cut the slice's list short, and a filament past its end read the first
filament's value. Each chain's root (a filament preset with no `inherits` that isn't a template;
`fdm_filament_common` in the BBL tree) therefore carries every filament setting at its default,
below its own keys and includes: the app's order again.

Fails, rather than slicing on a guess, on: a manifest whose version isn't the one expected, a
template that isn't in the manifest, a template that itself inherits or includes, a template key
whose default isn't known, and a value whose shape (list or scalar) differs from its default's.

usage: premerge.py --profiles DIR [--expect-version VERSION] --defaults defaults.json
                   --preset-cpp Preset.cpp --print-config-cpp PrintConfig.cpp --out DIR
"""

from __future__ import annotations

import argparse
import json
import math
import re
import shutil
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Literal, TypedDict

VENDOR = "BBL"
# A preset's own bookkeeping, not settings an include contributes (key_values, not config_src, in
# load_vendor_configs_from_json).
BOOKKEEPING = {
    "name",
    "inherits",
    "include",
    "instantiation",
    "type",
    "from",
    "setting_id",
    "filament_id",
    "description",
}
STRING_TYPES = {"coString", "coStrings"}

# A setting's value as the profile JSON and `--export-settings` serialise it: one string, or one
# string per entry for a vector option.
type Value = str | list[str]
# A preset file, or the default preset: setting name to serialised value. Bookkeeping keys
# (BOOKKEEPING) are strings too.
type Preset = dict[str, Value]
# One serialised entry, parsed the way ConfigOption::operator== compares it.
type Token = (
    tuple[Literal["s"], str]
    | tuple[Literal["nil"], None]
    | tuple[Literal["n", "%"], float]
)


class Skip(StrEnum):
    """Why a template key isn't applied, as premerge-report.json records it."""

    EQUAL_TO_DEFAULT = "equal_to_default"
    NOT_A_FILAMENT_OPTION = "not_a_filament_option"


@dataclass(frozen=True)
class Contribution:
    """What one template adds to a preset that includes it, and the keys it leaves out."""

    applied: Preset
    skipped: dict[Skip, list[str]]


class TemplateReport(TypedDict):
    applied: list[str]
    equal_to_default: list[str]
    not_a_filament_option: list[str]


class Report(TypedDict):
    version: str | None
    filament_presets_merged: int
    roots_given_defaults: dict[str, list[str]]
    templates: dict[str, TemplateReport]


class PremergeError(Exception):
    pass


def cpp_string_list(source: str, name: str) -> list[str]:
    """The string literals of the braced initialiser `name ... { ... };` in C++ `source`."""
    m = re.search(rf"\b{re.escape(name)}\s*(?:=\s*)?\{{(.*?)\}};", source, re.S)
    if m is None:
        raise PremergeError(f"no initialiser for {name} in the source")
    body = re.sub(r"/\*.*?\*/", "", m.group(1), flags=re.S)
    body = re.sub(r"//[^\n]*", "", body)
    items = re.findall(r'"([^"\\]*)"', body)
    if not items:
        raise PremergeError(f"{name} has no entries")
    return items


def string_typed_keys(print_config_cpp: str) -> set[str]:
    """Options PrintConfig.cpp declares as strings, compared as text rather than as numbers."""
    return {
        k
        for k, t in re.findall(
            r'this->add(?:_nullable)?\("([A-Za-z0-9_]+)",\s*(co[A-Za-z]+)\)',
            print_config_cpp,
        )
        if t in STRING_TYPES
    }


def filament_defaults(
    exported: Preset,
    options: list[str],
    override_keys: set[str],
) -> Preset:
    """The filament collection's default preset, as PresetBundle builds it."""
    out: Preset = {}
    for k in options:
        if k in override_keys:
            out[k] = ["nil"]
        elif k in exported:
            out[k] = exported[k]
    out["filament_settings_id"] = [""]
    return out


# The default preset's keys a chain's root doesn't take: the preset's identity and compatibility.
# When the CLI copies a filament's keys into the slice it skips the first three and reads the
# conditions only into its compatibility groups (BambuStudio.cpp, the filament loop), so they
# aren't settings it slices with, and a root's default would only blur what each preset declares.
NOT_SETTINGS = BOOKKEEPING | {
    "filament_settings_id",
    "compatible_printers",
    "compatible_prints",
    "compatible_printers_condition",
    "compatible_prints_condition",
}


def root_defaults(defaults: Preset) -> Preset:
    """What a chain's root carries below its own keys: every filament setting at its default."""
    return {k: v for k, v in defaults.items() if k not in NOT_SETTINGS}


def _token(v: str, text: bool) -> Token:
    if not isinstance(v, str):
        raise PremergeError(f"not a serialized value: {v!r}")
    s = v.strip()
    if text:
        return ("s", v)
    if s == "nil":
        return ("nil", None)
    pct = s.endswith("%")
    try:
        f = float(s[:-1] if pct else s)
    except ValueError:
        return ("s", v)  # an enum name
    if math.isnan(f):
        return ("nil", None)
    return ("%" if pct else "n", f)


def same(a: Value, b: Value, text: bool) -> bool:
    """ConfigOption::operator== on two serialized values (same option)."""
    if isinstance(a, str) or isinstance(b, str):
        if not (isinstance(a, str) and isinstance(b, str)):
            raise PremergeError(f"{a!r} and {b!r} differ in shape")
        return _token(a, text) == _token(b, text)
    return len(a) == len(b) and all(
        _token(x, text) == _token(y, text) for x, y in zip(a, b, strict=True)
    )


def template_keys(
    name: str,
    template: Preset,
    defaults: Preset,
    options: set[str],
    text_keys: set[str],
) -> Contribution:
    """The settings `template` contributes as an include, and what it leaves out and why."""
    if template.get("inherits") or template.get("include"):
        raise PremergeError(
            f"template {name!r} itself inherits or includes; premerge.py can't flatten that"
        )
    applied: Preset = {}
    skipped: dict[Skip, list[str]] = {why: [] for why in Skip}
    for k, v in template.items():
        if k in BOOKKEEPING:
            continue
        if k not in defaults:
            if k in options:
                raise PremergeError(f"template {name!r}: no default known for {k!r}")
            skipped[Skip.NOT_A_FILAMENT_OPTION].append(k)
            continue
        if same(v, defaults[k], k in text_keys):
            skipped[Skip.EQUAL_TO_DEFAULT].append(k)
            continue
        applied[k] = v
    return Contribution(applied, skipped)


def premerge(
    profiles: Path,
    defaults: Preset,
    options: set[str],
    text_keys: set[str],
    out: Path,
    expect_version: str | None = None,
) -> Report:
    """Write the merged tree to `out`; return the report."""
    src = profiles / VENDOR
    manifest_file = profiles / f"{VENDOR}.json"
    manifest = json.loads(manifest_file.read_text())
    if expect_version is not None and manifest.get("version") != expect_version:
        raise PremergeError(
            f"{VENDOR}.json is version {manifest.get('version')!r}, not {expect_version!r}"
        )
    if out.exists():
        shutil.rmtree(out)
    shutil.copytree(src, out / VENDOR, copy_function=shutil.copyfile)
    shutil.copyfile(manifest_file, out / f"{VENDOR}.json")
    for d in [out / VENDOR, *(p for p in (out / VENDOR).rglob("*") if p.is_dir())]:
        d.chmod(
            0o755
        )  # the store copy is read-only; copyfile already leaves files writable

    files = {e["name"]: e["sub_path"] for e in manifest["filament_list"]}
    presets: dict[str, Preset] = {
        name: json.loads((src / sub).read_text()) for name, sub in files.items()
    }
    templates = {
        t
        for p in presets.values()
        for t in (
            [p["include"]]
            if isinstance(p.get("include"), str)
            else p.get("include") or []
        )
    }
    root_keys = root_defaults(defaults)
    cache: dict[str, Contribution] = {}
    merged_presets = 0
    roots: dict[str, list[str]] = {}
    for name, sub in files.items():
        preset = presets[name]
        inc = preset.get("include")
        is_root = not preset.get("inherits") and name not in templates
        if not inc and not is_root:
            continue
        names = [] if not inc else [inc] if isinstance(inc, str) else inc
        # A chain's root carries every filament setting at its default, at the bottom: the app
        # starts every preset from the default preset, and the CLI copies only the keys a
        # filament's file holds, so a key no file in a filament's chain sets took another
        # filament's value or cut the slice's list short.
        merged: Preset = dict(root_keys) if is_root else {}
        for t in names:
            if t not in files:
                raise PremergeError(
                    f"{name!r} includes {t!r}, which isn't in {VENDOR}.json's filament_list"
                )
            if t not in cache:
                template: Preset = json.loads((src / files[t]).read_text())
                cache[t] = template_keys(t, template, defaults, options, text_keys)
            merged.update(cache[t].applied)
        merged.update({k: v for k, v in preset.items() if k != "include"})
        (out / VENDOR / sub).write_text(json.dumps(merged, indent=4) + "\n")
        if inc:
            merged_presets += 1
        if is_root:
            covered = set(preset).union(*(cache[t].applied for t in names))
            roots[name] = sorted(set(root_keys) - covered)
    return {
        "version": manifest.get("version"),
        "filament_presets_merged": merged_presets,
        "roots_given_defaults": roots,
        "templates": {
            t: {
                "applied": sorted(c.applied),
                "equal_to_default": sorted(c.skipped[Skip.EQUAL_TO_DEFAULT]),
                "not_a_filament_option": sorted(c.skipped[Skip.NOT_A_FILAMENT_OPTION]),
            }
            for t, c in sorted(cache.items())
        },
    }


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument(
        "--profiles",
        type=Path,
        required=True,
        help="Bambu Studio's profiles dir (holding BBL.json)",
    )
    ap.add_argument(
        "--expect-version",
        help="fail unless BBL.json's version is this one (the pinned package's)",
    )
    ap.add_argument(
        "--defaults",
        type=Path,
        required=True,
        help="`bambu-studio --export-settings` with no inputs",
    )
    ap.add_argument(
        "--preset-cpp",
        type=Path,
        required=True,
        help="src/libslic3r/Preset.cpp of the same version",
    )
    ap.add_argument(
        "--print-config-cpp",
        type=Path,
        required=True,
        help="src/libslic3r/PrintConfig.cpp, same version",
    )
    ap.add_argument("--out", type=Path, required=True)
    a = ap.parse_args(argv)

    print_config = a.print_config_cpp.read_text()
    options = cpp_string_list(a.preset_cpp.read_text(), "s_Preset_filament_options")
    overrides = set(cpp_string_list(print_config, "filament_extruder_override_keys"))
    # is_filament_extruder_override_key() adds this one by hand.
    if 'opt_key == "filament_retract_length_nc"' not in print_config:
        raise PremergeError(
            "is_filament_extruder_override_key changed; check which keys it adds"
        )
    overrides.add("filament_retract_length_nc")
    defaults = filament_defaults(json.loads(a.defaults.read_text()), options, overrides)
    report = premerge(
        a.profiles,
        defaults,
        set(options),
        string_typed_keys(print_config),
        a.out,
        a.expect_version,
    )
    (a.out / "premerge-report.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
