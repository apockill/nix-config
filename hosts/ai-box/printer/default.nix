# The Bambu X2D's services on ai-box (the lab-printer node in ai-box-apps wraps them):
#   bambuddy.nix      Bambuddy on 127.0.0.1:8070, and bambuddy.alexthiele.io for lab-printer's frame
#   slicer.nix        the native Bambu Studio CLI behind orca-slicer-api on 127.0.0.1:3001
#   profiles/         the slicer's profiles (the app's updated BBL package), filament templates merged
#   printer-add/      adds the X2D to Bambuddy, with its access code from 1Password
#
# Bambuddy and Bambu Studio come from nixpkgs-unstable (a flake input used only here): the
# box's release has no Bambuddy, and its Bambu Studio predates the X2D's profiles. They are
# built from their own nixpkgs instance with its default config, so they match
# cache.nixos.org instead of being rebuilt against the system's.
{
  inputs,
  lib,
  pkgs,
  ...
}:
let
  unstable = import inputs.nixpkgs-unstable {
    inherit (pkgs.stdenv.hostPlatform) system;
    # Bambu Studio's licence is AGPL plus the proprietary networking plugin it can download
    # (the slicer's sandbox has no network, so it never does).
    config.allowUnfreePredicate = pkg: lib.getName pkg == "bambu-studio";
  };
in
{
  imports = [
    ./bambuddy.nix
    ./slicer.nix
    ./printer-add
  ];

  options.aiBox.printer = {
    bambuddyPort = lib.mkOption {
      type = lib.types.port;
      default = 8070;
      internal = true;
      description = "Bambuddy's loopback port.";
    };
    slicerPort = lib.mkOption {
      type = lib.types.port;
      # Bambuddy's default Bambu Studio API URL is http://localhost:3001.
      default = 3001;
      internal = true;
      description = "The slicer API's loopback port.";
    };
  };

  config.nixpkgs.overlays = [
    (_: _: {
      inherit (unstable) bambu-studio;
      # 1.3.1 puts every filament of a multi-colour slice on one nozzle of a dual-nozzle
      # printer, so the X2D's second nozzle never prints. maziggy/bambuddy#3270 sends the
      # slicer a filament map: the caller's, or one planned from the spools the printer has
      # loaded (falling back to the old grouping when unclear). Backend only, so the
      # frontend stays the cached 1.3.1 one. The PR's diff, pinned to its head 6a42125c,
      # applies to 1.3.1 as is. It needs the slicer side in ./orca-slicer-api.nix.
      # https://github.com/maziggy/bambuddy/pull/3270
      # Remove once #3270 merges and nixpkgs' bambuddy includes it.
      bambuddy = unstable.bambuddy.overrideAttrs (old: {
        patches = (old.patches or [ ]) ++ [
          (pkgs.fetchpatch {
            name = "bambuddy-3270-dual-nozzle-filament-map.patch";
            url = "https://github.com/maziggy/bambuddy/compare/f3ae6fdd5755abd4e81dfa6cefcd9fbc0d7a2167...6a42125c3fcc995faead661066d88c9350cad852.diff";
            hash = "sha256-QiImiX0oiopZMpo1DvHvFD4I/i0gkdsPKD432jYBPoQ=";
          })
        ];
      });
    })
  ];
}
