# The Bambu X2D's services on ai-box (the lab-printer node in ai-box-apps wraps them):
#   slicer.nix        the native Bambu Studio CLI behind orca-slicer-api on 127.0.0.1:3001
#
# Bambu Studio comes from nixpkgs-unstable (a flake input used only here): the box's
# release has a Bambu Studio that predates the X2D's profiles. It is built from its own
# nixpkgs instance with its default config, as cache.nixos.org's packages are, instead of
# against the system's.
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
    ./slicer.nix
  ];

  options.aiBox.printer = {
    slicerPort = lib.mkOption {
      type = lib.types.port;
      # Bambuddy's default Bambu Studio API URL is http://localhost:3001.
      default = 3001;
      internal = true;
      description = "The slicer API's loopback port.";
    };
  };

  config.nixpkgs.overlays = [
    (_: _: { inherit (unstable) bambu-studio; })
  ];
}
