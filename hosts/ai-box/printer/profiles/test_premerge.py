"""Tests for premerge.py on a small profile tree. Run with `just test`; the build runs them too."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import premerge
import pytest

PRESET_CPP = """
static std::vector<std::string> s_Preset_filament_options {/*"filament_colour", */ "filament_type",
    "filament_retraction_length", "filament_retract_length_nc", // retract overrides
    "long_retractions_when_ec", "filament_extruder_variant", "slow_down_min_speed",
    "filament_notes", "inherits"};
"""
PRINT_CONFIG_CPP = """
const std::vector<std::string> filament_extruder_override_keys = {
    // floats
    "filament_retraction_length",
    "filament_z_hop"
};
bool is_filament_extruder_override_key(const std::string &opt_key)
{
    return std::find(...) != filament_extruder_override_keys.end() ||
           opt_key == "filament_retract_length_nc";
}
    def = this->add("filament_notes", coStrings);
    def = this->add("filament_extruder_variant", coStrings);
    def = this->add_nullable("long_retractions_when_ec", coBools);
"""
EXPORTED = {
    "filament_type": ["PLA"],
    "long_retractions_when_ec": ["0"],
    "filament_extruder_variant": ["Direct Drive Standard"],
    "slow_down_min_speed": ["10"],
    "filament_notes": [""],
    "filament_retract_length_nc": ["10"],
    "wall_loops": "2",  # a process key: not part of the filament defaults
}
# The filament defaults (EXPORTED on the filament options, override keys nil) a chain's root takes;
# filament_settings_id, also in the default preset, is the preset's identity and stays out.
ROOT_DEFAULTS = {
    "filament_type": ["PLA"],
    "filament_retraction_length": ["nil"],
    "filament_retract_length_nc": ["nil"],
    "long_retractions_when_ec": ["0"],
    "filament_extruder_variant": ["Direct Drive Standard"],
    "slow_down_min_speed": ["10"],
    "filament_notes": [""],
}


def write_tree(
    root: Path,
    filaments: dict[str, dict[str, Any]],
    subdir: dict[str, str] | None = None,
) -> Path:
    """A profiles dir with BBL.json, BBL/filament/* and one machine preset with an include."""
    subdir = subdir or {}
    bbl = root / "profiles" / "BBL"
    (bbl / "filament" / "sub").mkdir(parents=True)
    (bbl / "machine").mkdir()
    entries = []
    for name, body in filaments.items():
        sub = f"filament/{subdir.get(name, '')}{name}.json"
        (bbl / sub).write_text(json.dumps({"name": name, "type": "filament", **body}))
        entries.append({"name": name, "sub_path": sub})
    machine = {
        "name": "X",
        "type": "machine",
        "include": ["X template machine_start_gcode"],
    }
    (bbl / "machine" / "X.json").write_text(json.dumps(machine))
    manifest = {
        "name": "BBL",
        "version": "1",
        "filament_list": entries,
        "machine_list": [{"name": "X", "sub_path": "machine/X.json"}],
    }
    (root / "profiles" / "BBL.json").write_text(json.dumps(manifest))
    return root / "profiles"


TEMPLATE = {
    "instantiation": "false",
    "from": "system",
    "filament_extruder_variant": ["Direct Drive Standard", "Bowden Standard"],
    "long_retractions_when_ec": ["1", "1"],
    "slow_down_min_speed": ["10", "10"],
    "filament_retraction_length": ["nil", "nil"],
}


def run(
    tmp_path: Path, filaments: dict[str, dict[str, Any]], **kw: Any
) -> tuple[Path, dict[str, Any]]:
    profiles = write_tree(tmp_path, filaments, kw.pop("subdir", None))
    (tmp_path / "defaults.json").write_text(json.dumps(kw.pop("exported", EXPORTED)))
    (tmp_path / "Preset.cpp").write_text(PRESET_CPP)
    (tmp_path / "PrintConfig.cpp").write_text(PRINT_CONFIG_CPP)
    out = tmp_path / "out"
    args = [
        "--profiles",
        str(profiles),
        "--defaults",
        str(tmp_path / "defaults.json"),
        "--out",
        str(out),
    ]
    args += [
        "--preset-cpp",
        str(tmp_path / "Preset.cpp"),
        "--print-config-cpp",
        str(tmp_path / "PrintConfig.cpp"),
    ]
    premerge.main(args)
    return out / "BBL", json.loads((out / "premerge-report.json").read_text())


def load(bbl: Path, sub: str) -> dict[str, Any]:
    result: dict[str, Any] = json.loads((bbl / "filament" / f"{sub}.json").read_text())
    return result


def test_cpp_string_list_skips_comments() -> None:
    assert premerge.cpp_string_list(PRESET_CPP, "s_Preset_filament_options")[:3] == [
        "filament_type",
        "filament_retraction_length",
        "filament_retract_length_nc",
    ]
    with pytest.raises(premerge.PremergeError, match="no initialiser"):
        premerge.cpp_string_list(PRESET_CPP, "missing_list")


def test_same_follows_config_option_equality() -> None:
    assert not premerge.same(
        ["10", "10"], ["10"], False
    )  # vectors of another length differ
    assert premerge.same(["10.0"], ["10"], False)
    assert premerge.same(["nil", "nil"], ["nil", "nil"], False)
    assert not premerge.same(["nil"], ["0"], False)
    assert not premerge.same(["50%"], ["50"], False)
    assert not premerge.same(["1.0"], ["1"], True)  # string options compare as text
    assert premerge.same("Normal Lift", "Normal Lift", False)
    with pytest.raises(premerge.PremergeError, match="shape"):
        premerge.same(["1"], "1", False)


def test_template_merged_below_own_keys(tmp_path: Path) -> None:
    bbl, report = run(
        tmp_path,
        {
            "fdm_filament_template_direct_bowden": TEMPLATE,
            "PLA @base": {"inherits": "", "filament_type": ["PLA"]},
            "PLA @X2D": {
                "inherits": "PLA @base",
                "include": ["fdm_filament_template_direct_bowden"],
                "long_retractions_when_ec": ["0", "1"],
            },
        },
    )
    merged = load(bbl, "PLA @X2D")
    assert "include" not in merged
    assert merged["inherits"] == "PLA @base"
    assert merged["filament_extruder_variant"] == [
        "Direct Drive Standard",
        "Bowden Standard",
    ]
    assert merged["long_retractions_when_ec"] == [
        "0",
        "1",
    ]  # the preset's own value wins
    assert merged["filament_retraction_length"] == ["nil", "nil"]
    assert "instantiation" not in merged
    assert load(bbl, "PLA @base") == {
        **ROOT_DEFAULTS,
        "name": "PLA @base",
        "type": "filament",
        "inherits": "",
        "filament_type": ["PLA"],
    }
    assert report["filament_presets_merged"] == 1
    assert (
        report["templates"]["fdm_filament_template_direct_bowden"]["equal_to_default"]
        == []
    )
    # The machine preset's include is left for the resolver's companion lookup.
    assert json.loads((bbl / "machine" / "X.json").read_text())["include"] == [
        "X template machine_start_gcode"
    ]


def test_template_key_equal_to_default_leaves_the_parents_value(tmp_path: Path) -> None:
    template = {
        **TEMPLATE,
        "slow_down_min_speed": ["10"],
        "filament_retraction_length": ["nil"],
        "filament_retract_length_nc": [
            "nil"
        ],  # nil too, though FullPrintConfig's default is 10
    }
    bbl, report = run(
        tmp_path,
        {
            "fdm_filament_template_direct_dual": template,
            "PLA": {
                "inherits": "PLA @base",
                "include": "fdm_filament_template_direct_dual",
            },
            "PLA @base": {
                "slow_down_min_speed": ["20"],
                "filament_retraction_length": ["1.5"],
            },
        },
    )
    merged = load(bbl, "PLA")
    assert (
        "slow_down_min_speed" not in merged
    )  # equal to the default 10: PLA @base's 20 stays
    assert (
        "filament_retraction_length" not in merged
    )  # an override key: its default is nil
    assert merged["long_retractions_when_ec"] == ["1", "1"]
    assert report["templates"]["fdm_filament_template_direct_dual"][
        "equal_to_default"
    ] == [
        "filament_retract_length_nc",
        "filament_retraction_length",
        "slow_down_min_speed",
    ]


def test_a_parents_include_is_merged_at_the_parents_level(tmp_path: Path) -> None:
    bbl, _ = run(
        tmp_path,
        {
            "fdm_filament_template_direct_dual": TEMPLATE,
            "PLA @base": {
                "include": ["fdm_filament_template_direct_dual"],
                "long_retractions_when_ec": ["0", "0"],
            },
            "PLA": {"inherits": "PLA @base", "filament_type": ["PLA"]},
        },
        subdir={"PLA @base": "sub/"},
    )
    assert (
        load(bbl, "sub/PLA @base")["filament_extruder_variant"]
        == TEMPLATE["filament_extruder_variant"]
    )
    assert load(bbl, "sub/PLA @base")["long_retractions_when_ec"] == ["0", "0"]
    assert "filament_extruder_variant" not in load(bbl, "PLA")


def test_keys_outside_the_filament_options_are_dropped(tmp_path: Path) -> None:
    bbl, report = run(
        tmp_path,
        {
            "fdm_filament_template_direct_dual": {**TEMPLATE, "wall_loops": "3"},
            "PLA": {"include": ["fdm_filament_template_direct_dual"]},
        },
    )
    assert "wall_loops" not in load(bbl, "PLA")
    assert report["templates"]["fdm_filament_template_direct_dual"][
        "not_a_filament_option"
    ] == ["wall_loops"]


def resolve(bbl: Path, name: str) -> dict[str, Any]:
    """orca-slicer-api's inherits walk (profile-resolver.js resolveProfile): parent below child."""
    files = {p.stem: p for p in (bbl / "filament").rglob("*.json")}
    current: dict[str, Any] = json.loads(files[name].read_text())
    while current.get("inherits"):
        parent = json.loads(files[current["inherits"]].read_text())
        current = {**parent, **current, "inherits": parent.get("inherits", "")}
    return current


def test_a_chains_root_carries_every_filament_setting_at_its_default(
    tmp_path: Path,
) -> None:
    bbl, report = run(
        tmp_path,
        {
            "fdm_filament_template_direct_dual": TEMPLATE,
            "fdm_filament_common": {"instantiation": "false", "filament_type": ["ABS"]},
            "PLA Pure @base": {
                "inherits": "fdm_filament_common",
                "filament_notes": ["pure"],
            },
            "PLA Pure": {
                "inherits": "PLA Pure @base",
                "include": ["fdm_filament_template_direct_dual"],
            },
            "PLA Basic": {"inherits": "fdm_filament_common"},
        },
    )
    # Below the root's own keys; identity keys aren't settings and stay out.
    assert load(bbl, "fdm_filament_common") == {
        **ROOT_DEFAULTS,
        "name": "fdm_filament_common",
        "type": "filament",
        "instantiation": "false",
        "filament_type": ["ABS"],
    }
    # Only the root: the other files still hold just what they declare.
    assert load(bbl, "PLA Basic") == {
        "name": "PLA Basic",
        "type": "filament",
        "inherits": "fdm_filament_common",
    }
    assert load(bbl, "fdm_filament_template_direct_dual") == {
        "name": "fdm_filament_template_direct_dual",
        "type": "filament",
        **TEMPLATE,
    }
    # The key only one chain sets reaches the other filament's file at its default, so the CLI
    # gets a value for every filament instead of padding with the first one's.
    assert resolve(bbl, "PLA Pure")["filament_notes"] == ["pure"]
    assert resolve(bbl, "PLA Basic")["filament_notes"] == [""]
    # A chain's own and template values still win over the root's defaults.
    assert (
        resolve(bbl, "PLA Pure")["filament_extruder_variant"]
        == TEMPLATE["filament_extruder_variant"]
    )
    assert resolve(bbl, "PLA Basic")["filament_type"] == ["ABS"]
    assert report["roots_given_defaults"] == {
        "fdm_filament_common": sorted(set(ROOT_DEFAULTS) - {"filament_type"})
    }


@pytest.mark.parametrize(
    ("filaments", "message"),
    [
        ({"PLA": {"include": ["fdm_filament_template_gone"]}}, "isn't in BBL.json"),
        (
            {
                "fdm_filament_template_direct_dual": {
                    **TEMPLATE,
                    "inherits": "fdm_filament_common",
                },
                "fdm_filament_common": {},
                "PLA": {"include": ["fdm_filament_template_direct_dual"]},
            },
            "itself inherits or includes",
        ),
        (
            {
                "fdm_filament_template_direct_dual": {**TEMPLATE, "include": ["other"]},
                "other": {},
                "PLA": {"include": ["fdm_filament_template_direct_dual"]},
            },
            "itself inherits or includes",
        ),
        (
            {
                "fdm_filament_template_direct_dual": {
                    **TEMPLATE,
                    "filament_notes": ["x"],
                },
                "PLA": {"include": ["fdm_filament_template_direct_dual"]},
            },
            "no default known for 'filament_notes'",
        ),
    ],
)
def test_fails_loudly(
    tmp_path: Path, filaments: dict[str, dict[str, Any]], message: str
) -> None:
    exported = {k: v for k, v in EXPORTED.items() if k != "filament_notes"}
    with pytest.raises(premerge.PremergeError, match=message):
        run(tmp_path, filaments, exported=exported)
