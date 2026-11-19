# Pre-merged slicer profiles

This directory builds a copy of Bambu's BBL profiles: the updated package the Bambu Studio app installs when it accepts its profile update, not the older set bundled with the app. In the copy, each filament preset already contains the settings of the templates it `include`s, merged the way the Bambu Studio app merges them. `../slicer.nix` points the slicer service (orca-slicer-api, which Bambuddy slices through) at this copy with `BUNDLED_PROFILES_PATH`.

## The profiles

**Which ones.** The app ships with a set of profiles (02.08.00.01 in Bambu Studio 02.08.00.50) and, on start, asks Bambu which newer package goes with its version. A person who accepts the offer slices with the newer package, so that is the one we pin (Alex, 2026-11-18). Among its changes over the bundled set:
- the X2D machine start sequence no longer sends `M620.17 T1 S220 L-1` for an unused nozzle;
- the X2D filament-change and layer-change templates set new chamber auto-cooling thresholds (`M142`), for example PETG on a 0.4 nozzle `R50 S55 … O55` where the bundled set had `R35 S50 … O55`.

**How the app asks** (Bambu Studio 02.08.00.50, `PresetUpdater::priv::sync_config` and `sync_resources` in `src/slic3r/Utils/PresetUpdater.cpp`, the URL from `GUI_App::get_http_url`):
```
GET https://api.bambulab.com/v1/iot-service/api/slicer/resource?slicer/settings/bbl=02.08.00.00
```
The query is the app's version with its last two parts zeroed. The answer names the package's `version` and `url`; the app downloads the zip only if that version shares the app's major.minor and is newer than what it has, unzips it into its HOME's `ota/`, and on acceptance copies it into `system/` as `BBL.json` and `BBL/`.

**The pin.** `default.nix` fetches that zip with `fetchzip` and a fixed hash, so nothing is downloaded at runtime and the tree is reproducible. Its top level is `BBL.json` and `BBL/`, the same layout as the profiles directory the app bundles. On 2026-11-18 the endpoint answered 02.08.00.06 (`.../settings/BBL/02.08.00.06/9d40efa30a/02.08.00.06.zip`); no newer package exists for 02.08.

**The name.** The output is `bambu-studio-profiles-premerged-<bambu-studio version>-bbl-<profiles version>`, for example `bambu-studio-profiles-premerged-02.08.00.50-bbl-02.08.00.06`: the CLI that slices and the profiles it slices with have separate versions, and both change what a slice holds. The profiles' version is also in the output as `bbl-version` (the BBL.json `version`) and on the derivation as `bblVersion`; the unmerged package is the derivation's `bbl` and the output's `bbl-package` link.

**Bambu's GitHub source** is not the pin. The bambulab/BambuStudio repository's `release/20260929` branch set BBL.json to 02.08.00.06 in commit 8945dc4c7c (2026-08-26) and has since moved on to 02.08.00.09, which the endpoint doesn't offer the 02.08.00.50 app. The app installs the endpoint's zip, so that is what we pin.

## The problem it fixes

Bambu's filament profiles are layered. Take "Bambu PLA Basic @BBL X2D 0.4 nozzle":
- It **inherits** from more general PLA and filament presets.
- It **includes** a shared template, `fdm_filament_template_direct_bowden` (or `..._direct_dual` on other printers).

The template is the only place that lists the nozzle types the preset's values are written for: Direct Drive Standard, Direct Drive High Flow, Bowden Standard and Bowden High Flow. Retraction, temperatures and similar settings hold one value per type, in that order.

The Bambu Studio app applies both layers. Bambu Studio's command-line tool, which the slicer service runs, takes each preset as a single finished file. orca-slicer-api builds those files itself, and its resolver follows `inherits` but ignores `include`. So every filament was sliced as if it were on a direct-drive nozzle. Found on 2026-11-16:
- **Stringing:** on the X2D's right (Bowden) nozzle, white PLA retracted 0.4 mm instead of 3 mm and strung badly.
- **Start temperatures:** the start sequence's lookups landed on the wrong filament's values. On a four-colour plate, white PLA was heated, purged and wiped at PETG's 245–250 °C instead of 220 °C.

## How it fixes it

`premerge.py` copies the BBL tree. For every filament preset with an `include`, it writes the template's settings into the preset's own file, below the preset's own keys. The resolver's unchanged `inherits` walk then puts the parent below those. The result is the app's order: parent, then templates, then the preset's own keys (`PresetBundle::load_vendor_configs_from_json` in Bambu Studio's `src/libslic3r/PresetBundle.cpp`).

It copies the app's rule exactly. A template key is applied only if it differs from the default filament preset; otherwise the parent's value stays.
- **Default values:** taken from the shipped binary itself (`bambu-studio --export-settings` with no inputs, in the build).
- **Key list and nil overrides:** read from the same version's source (`Preset.cpp`, `PrintConfig.cpp`).
- **Equality:** follows `ConfigOption::operator==`.

For the 02.08.00.06 profiles with Bambu Studio 02.08.00.50's defaults, every template key differs from its default, so every key is applied: 1500 filament presets merged from four templates (`fdm_filament_template_direct_bowden`, `..._direct_dual` and their `_e3d` variants, 37 or 39 keys each). `premerge-report.json` in the output lists, per template, what was applied and what was skipped and why.

The build fails instead of guessing when:
- the package's BBL.json isn't the pinned version;
- bambu-studio's major.minor differs from the pinned package's (the app would install another package);
- the CLI's own `BBL/cli_config.json` differs from the package's (below);
- a template is missing;
- a template itself inherits or includes;
- a default is unknown;
- a value's shape doesn't match its default's;
- Bambu changes how the nil override keys are defined.

Machine presets also use `include`, for their G-code templates. orca-slicer-api already applies those by name, so they're copied unchanged. Process presets have no includes.

**What the CLI reads from its own install.** orca-slicer-api hands the CLI every printer, process and filament preset, resolved from this tree. The one profile file the CLI still opens from its own `share/BambuStudio/profiles` is `BBL/cli_config.json`, the CLI-only caps on machine limits; 02.08.00.06's copy is byte-identical to the bundled one, and the build checks that it stays so. Its `machine_full/`, `filament_full/` and `process_full/` lookups are for files the package doesn't contain, so they never apply.

We chose this over patching orca-slicer-api (nix-config #96). A profile copy can't conflict with a wrapper update, and it rebuilds by itself when Bambu Studio or the pinned package changes.

## How we know it works

- **Unit tests:** `test_premerge.py` runs in the build and with `just test`. It covers:
  - the default-equality rule, including nil overrides;
  - own keys winning;
  - a parent's include merging at the parent's level;
  - non-filament keys being dropped;
  - every fail-loud case.

  Replacing the rule with "apply every key" fails a test.
- **Every preset resolves like the patched resolver** (02.08.00.01, 2026-11-16): all 1873 BBL filament presets resolve identically through #96's patched resolver on the stock tree and through the unpatched resolver on this tree. The control, unpatched on the stock tree, differs on 1364 of them.
- **A/B print** (2026-11-16, `workspace/prints/ab-bowden/` on ai-box). Two thin towers in white PLA on the right nozzle:
  - unfixed: a dense web of strings;
  - fixed: clean.

  This tree gives the fixed retraction (3 mm, Bowden Standard), with 02.08.00.01 and with 02.08.00.06 alike.
- **The pin is what the app installs** (2026-11-18): a fresh Bambu Studio 02.08.00.50 HOME (ai-box-apps' golden regeneration, display :97) went through the first-run wizard and was offered "BBL 2.8.0.6"; after OK, its `system/BBL.json` and `system/BBL/` (2517 files) were byte-identical to this pin's package (`diff -r`, `cmp`), and so was the download it kept in `ota/presets/`.
- **The slice uses the pinned package** (2026-11-18): through a private orca-slicer-api on its own port, given this tree and the presets Bambuddy sends (stubs naming the stock presets), traced with `strace -f`:
  - towers-right-plabasic (white PLA Basic on the right nozzle) sends `M620.17 T1 S220 L0` where the 02.08.00.01 tree sent `L-1`;
  - pair-petg-left (PETG Basic and PETG HF on the left nozzle) sets `M142 P1 R50 S55 U0 V0.5 O55` at its layer changes where the 02.08.00.01 tree set `R35 S50`;
  - the CLI opened nothing under its own `share/BambuStudio/profiles` but `BBL/cli_config.json` (above).
- **App goldens:** slices made in the real Bambu Studio app and committed in ai-box-apps (`apps/printer/tests/goldens/`, `test_slice_goldens.py`). The same cases sliced through our stack with this tree have to match them. Anything that doesn't is a finding.

## When Bambu Studio or its profiles update

- **Bambu Studio, same major.minor** (02.08.00.50 to 02.08.01.x): the app asks the endpoint the same question, so the pin stays. The derivation reruns against the new binary and source, with its tests and fail-loud checks.
- **Bambu Studio, new major.minor:** the build fails until the pin is moved. Ask the endpoint with the new version (the query above), pin the zip it names (`bblVersion`, the URL and the hash in `default.nix`), and build.
- **A newer package for the same app:** pin it the same way. `../profile-canary/` watches for one: daily it asks the endpoint the app's question and, once per newer version, slices a towered and a one-filament case with that package and with the pinned one through a private orca-slicer-api, and reports the difference to Alex (template and program lines, print time, filament). It switches nothing.

Then rerun the golden suite in ai-box-apps, and regenerate the app goldens with its `regen/` scripts, the app's HOME taking the same package.
