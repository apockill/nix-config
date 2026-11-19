# Bambu Studio's stock BBL profiles with each filament preset's `include` templates merged into
# the preset, the way the Bambu Studio app applies them (./premerge.py has the rule and the
# source lines). ../slicer.nix points orca-slicer-api's BUNDLED_PROFILES_PATH here: its resolver
# walks `inherits` only, and the CLI doesn't apply includes in a preset file it's given, so
# without this a filament on the X2D's right (Bowden) nozzle sliced with Direct Drive settings.
#
# The app applies only the template keys that differ from the default filament preset. Those
# defaults come from the shipped binary, not from parsing C++ initialisers: with no inputs,
# `bambu-studio --export-settings` writes FullPrintConfig's defaults, the config the app's default
# filament preset is copied from. Preset::filament_options() and the override keys PresetBundle
# sets to nil are plain string lists, read from the same version's source (nixpkgs' patches to it
# only touch the build). premerge-report.json lists, per template, what it applied and what it
# left to the parent; for 02.08.00.50 that's every key, as every template value is a 2- or
# 4-entry list and every default a 1-entry one.
#
# The root of the filament chains (fdm_filament_common) also gets every filament setting at that
# default, below its own keys: the app starts each preset from the default preset, while the CLI
# copies only the keys a filament's file holds and pads a short list with the first filament's
# value (pre_start_fan_time, which only Bambu PLA Pure sets, spread to every filament).
{
  lib,
  bambu-studio,
  python3,
  runCommand,
}:
runCommand "bambu-studio-profiles-premerged-${bambu-studio.version}"
  {
    nativeBuildInputs = [ (python3.withPackages (ps: [ ps.pytest ])) ];
  }
  ''
    cp ${./premerge.py} premerge.py
    cp ${./test_premerge.py} test_premerge.py
    python3 -m pytest -q -p no:cacheprovider test_premerge.py

    # The CLI exits 0 whatever happens and reports in result.json.
    HOME=$TMPDIR ${lib.getExe bambu-studio} --export-settings $PWD/defaults.json > export.log 2>&1 \
      || { cat export.log; exit 1; }
    grep -q '"return_code": 0' result.json || { cat result.json export.log; exit 1; }

    python3 premerge.py \
      --profiles ${bambu-studio}/share/BambuStudio/profiles \
      --defaults defaults.json \
      --preset-cpp ${bambu-studio.src}/src/libslic3r/Preset.cpp \
      --print-config-cpp ${bambu-studio.src}/src/libslic3r/PrintConfig.cpp \
      --out $out > /dev/null
    cp defaults.json $out/bambu-studio-defaults.json
  ''
