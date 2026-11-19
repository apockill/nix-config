# Pre-merged slicer profiles

This directory builds a copy of Bambu Studio's stock BBL profiles. In the copy, each filament preset already contains the settings of the templates it `include`s, merged the way the Bambu Studio app merges them. `../slicer.nix` points the slicer service (orca-slicer-api, which Bambuddy slices through) at this copy with `BUNDLED_PROFILES_PATH`.

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

For 02.08.00.50, every template key differs from its default, so every key is applied. `premerge-report.json` in the output lists, per template, what was applied and what was skipped and why.

The build fails instead of guessing when:
- a template is missing;
- a template itself inherits or includes;
- a default is unknown;
- a value's shape doesn't match its default's;
- Bambu changes how the nil override keys are defined.

It also gives the root of the filament chains, `fdm_filament_common`, every filament setting at the default, below its own keys. The app starts every preset from the default filament preset, so a setting nothing in a chain sets is the default. The CLI starts from nothing: it copies into the slice only the keys each filament's file holds (`src/BambuStudio.cpp`, the filament loop), and when a list ends early, a filament past its end reads the first filament's value (`ConfigOptionVector::set_at`/`get_at` in `src/libslic3r/Config.hpp`). Found on 2026-11-18 by the app goldens:
- **Pre-start fan:** only Bambu PLA Pure's presets set `pre_start_fan_time` (2 s). With PLA Pure first, every other filament on the plate got its part fan 2 s early (door-sock two-colour); with it second, the slice's list stopped at it (`0,2` where the app has `0,2,0,0`).
- **The same fault in other keys:** `fdm_filament_common` lacked 12 filament settings. No BBL preset sets 8 of them, so every filament already sliced with the default and only the list's length changes. The other 4 are set by some chains only, so a mixed plate could hit the same fault: `pre_start_fan_time`, `first_x_layer_fan_speed` (40 in 128 X2D presets, unset in 58), `filament_adhesiveness_category` and `filament_change_length_nc`. `premerge-report.json` lists the 12 under `roots_given_defaults`.

Machine presets also use `include`, for their G-code templates. orca-slicer-api already applies those by name, so they're copied unchanged. Process presets have no includes.

We chose this over patching orca-slicer-api (nix-config #96). A profile copy can't conflict with a wrapper update, and it rebuilds by itself when Bambu Studio updates.

## How we know it works

- **Unit tests:** `test_premerge.py` runs in the build and with `just test`. It covers:
  - the default-equality rule, including nil overrides;
  - own keys winning;
  - a parent's include merging at the parent's level;
  - non-filament keys being dropped;
  - every fail-loud case.

  Replacing the rule with "apply every key" fails a test.
- **Every preset resolves like the patched resolver:** all 1873 BBL filament presets resolve identically through #96's patched resolver on the stock tree and through the unpatched resolver on this tree. The control, unpatched on the stock tree, differs on 1364 of them.
- **A/B print** (2026-11-16, `workspace/prints/ab-bowden/` on ai-box). Two thin towers in white PLA on the right nozzle:
  - unfixed: a dense web of strings;
  - fixed: clean.

  This tree gives the fixed retraction (3 mm, Bowden Standard).
- **App goldens:** slices made in the real Bambu Studio app and committed in ai-box-apps (`apps/printer/tests/goldens/`, `test_slice_goldens.py`). The same cases sliced through our stack with this tree have to match them. Anything that doesn't is a finding.

## When Bambu Studio updates

Nothing to do by hand. The derivation reruns against the new package, and its tests and fail-loud checks run in the build. Then rerun the golden suite, and regenerate the app goldens with its `regen/` scripts if the app's output changed.
