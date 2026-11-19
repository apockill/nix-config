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
        *(
            ["--expect-version", kw.pop("expect_version")]
            if "expect_version" in kw
            else []
        ),
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


def test_the_manifest_must_be_the_expected_version(tmp_path: Path) -> None:
    filaments = {"PLA": {"filament_type": ["PLA"]}}
    run(tmp_path / "same", filaments, expect_version="1")
    with pytest.raises(premerge.PremergeError, match="version '1', not '2'"):
        run(tmp_path / "other", filaments, expect_version="2")
