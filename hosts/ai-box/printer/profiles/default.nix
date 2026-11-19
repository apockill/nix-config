# Bambu's updated BBL profiles, the package the Bambu Studio app installs when it accepts its
# preset update, with each filament preset's `include` templates merged into the preset the way
# the app applies them (./premerge.py has the rule and the source lines). ../slicer.nix points
# orca-slicer-api's BUNDLED_PROFILES_PATH here: its resolver walks `inherits` only, and the CLI
# doesn't apply includes in a preset file it's given, so without this a filament on the X2D's
# right (Bowden) nozzle sliced with Direct Drive settings.
#
# 1. The profiles (`bbl`): the app asks Bambu's update endpoint which preset package goes with
#    its version (README, The profiles) and downloads a zip holding BBL.json and BBL/. That zip
#    is pinned here by its hash. The build fails if its BBL.json carries another version, if
#    bambu-studio's major.minor no longer matches the package's (the app only installs a package
#    of its own major.minor), or if the CLI's own BBL/cli_config.json differs from the package's.
# 2. The defaults: the app applies only the template keys that differ from the default filament
#    preset. Those come from the shipped binary, not from parsing C++ initialisers: with no
#    inputs, `bambu-studio --export-settings` writes FullPrintConfig's defaults, the config the
#    app's default filament preset is copied from. Preset::filament_options() and the override
#    keys PresetBundle sets to nil are plain string lists, read from the same version's source
#    (nixpkgs' patches to it only touch the build).
# 3. The root of the filament chains (fdm_filament_common) also gets every filament setting at
#    that default, below its own keys: the app starts each preset from the default preset, while
#    the CLI copies only the keys a filament's file holds and pads a short list with the first
#    filament's value (pre_start_fan_time, which only Bambu PLA Pure sets, spread to every
#    filament).
# 4. The output: the merged BBL/ and BBL.json, premerge-report.json (per template, what was
#    applied and what was left to the parent; per root, the defaults it was given),
#    bambu-studio-defaults.json, bbl-version, the profiles' version for anything that reads this
#    tree, and bbl-package, the unmerged package (ai-box-apps' golden regeneration seeds the
#    Bambu Studio app's HOME with it). The name carries both versions, the CLI's and the
#    profiles': bambu-studio-profiles-premerged-<bambu-studio>-bbl-<profiles>.
{
  lib,
  bambu-studio,
  fetchzip,
  python3,
  runCommand,
}:
let
  # The version the update endpoint offered Bambu Studio 02.08.00.50 on 2026-11-18, and the
  # package's URL from the same answer (the path segment after the version is Bambu's, not ours).
  bblVersion = "02.08.00.06";
  bbl = fetchzip {
    name = "bambu-bbl-profiles-${bblVersion}";
    url = "https://public-cdn.bblmw.com/upgrade/studio/settings/BBL/${bblVersion}/9d40efa30a/${bblVersion}.zip";
    # The zip's top level is BBL.json and BBL/, the layout premerge.py's --profiles takes.
    stripRoot = false;
    hash = "sha256-BsDthPJtqaLl0idoa62XBDWTFY37rtwyIA8cx7nR+8o=";
  };
  # Preset.cpp and PrintConfig.cpp of the slicer's own source: the two files premerge.py reads.
  presetSources = runCommand "bambu-studio-preset-sources-${bambu-studio.version}" { } ''
    mkdir -p $out
    cp ${bambu-studio.src}/src/libslic3r/{Preset,PrintConfig}.cpp $out/
  '';
in
assert lib.assertMsg
  (lib.versions.majorMinor bambu-studio.version == lib.versions.majorMinor bblVersion)
  "bambu-studio ${bambu-studio.version} installs only ${lib.versions.majorMinor bambu-studio.version}.x profiles, but ${bblVersion} is pinned: pin the package its update endpoint offers (profiles/README.md)";
runCommand "bambu-studio-profiles-premerged-${bambu-studio.version}-bbl-${bblVersion}"
  {
    nativeBuildInputs = [ (python3.withPackages (ps: [ ps.pytest ])) ];
    passthru = { inherit bbl bblVersion presetSources; };
  }
  ''
    cp ${./premerge.py} premerge.py
    cp ${./test_premerge.py} test_premerge.py
    python3 -m pytest -q -p no:cacheprovider test_premerge.py

    # The CLI exits 0 whatever happens and reports in result.json.
    HOME=$TMPDIR ${lib.getExe bambu-studio} --export-settings $PWD/defaults.json > export.log 2>&1 \
      || { cat export.log; exit 1; }
    grep -q '"return_code": 0' result.json || { cat result.json export.log; exit 1; }

    # The one profile file the CLI reads from its own install rather than from the presets
    # orca-slicer-api gives it: the CLI-only machine limit caps. Same as the pinned package's, or
    # a slice would mix the two versions.
    cmp ${bambu-studio}/share/BambuStudio/profiles/BBL/cli_config.json ${bbl}/BBL/cli_config.json \
      || { echo "bambu-studio's bundled BBL/cli_config.json differs from ${bblVersion}'s (profiles/README.md)"; exit 1; }

    python3 premerge.py \
      --profiles ${bbl} \
      --expect-version ${bblVersion} \
      --defaults defaults.json \
      --preset-cpp ${presetSources}/Preset.cpp \
      --print-config-cpp ${presetSources}/PrintConfig.cpp \
      --out $out > /dev/null
    cp defaults.json $out/bambu-studio-defaults.json
    echo ${bblVersion} > $out/bbl-version
    ln -s ${bbl} $out/bbl-package
  ''
