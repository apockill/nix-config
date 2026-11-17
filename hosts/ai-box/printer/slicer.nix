# The slicer Bambuddy slices with: orca-slicer-api (./orca-slicer-api.nix), the HTTP
# wrapper Bambuddy's slicer sidecar images run, with nixpkgs' native aarch64 Bambu Studio
# CLI as its slicer. Bambuddy (./bambuddy.nix) posts the model and the preset JSONs to
# POST /slice; the wrapper flattens each preset's `inherits` chain from Bambu Studio's
# stock profiles (BUNDLED_PROFILES_PATH) and runs the CLI in a temporary directory.
# Those profiles are ./profiles: the stock ones with each filament preset's `include`
# templates merged in as the Bambu Studio app does, since the wrapper walks `inherits` only.
#
# Loopback only, and the sandbox allows no other network traffic: slicing needs none.
{
  config,
  lib,
  pkgs,
  ...
}:
let
  cfg = config.aiBox.printer;
  orca-slicer-api = pkgs.callPackage ./orca-slicer-api.nix { };
  profiles = pkgs.callPackage ./profiles { };
in
{
  systemd.services.bambu-studio-api = {
    description = "Bambu Studio slicer API for Bambuddy";
    wantedBy = [ "multi-user.target" ];
    after = [ "network.target" ];

    # mkfifo, for the CLI's progress pipe.
    path = [ pkgs.coreutils ];
    environment = {
      HOST = "127.0.0.1";
      PORT = toString cfg.slicerPort;
      ORCASLICER_PATH = lib.getExe pkgs.bambu-studio;
      BUNDLED_PROFILES_PATH = "${profiles}/BBL";
      # Profiles stored through the wrapper's own /profiles API; Bambuddy sends its
      # presets with each slice instead, so this stays empty.
      DATA_PATH = "/var/lib/bambu-studio-api";
      # A DynamicUser has no home; the CLI writes nothing there, but if it ever does, it
      # lands here rather than failing.
      HOME = "/var/lib/bambu-studio-api";
    };

    serviceConfig = {
      ExecStart = lib.getExe orca-slicer-api;
      DynamicUser = true;
      StateDirectory = "bambu-studio-api";
      # Each slice works in a fresh directory under /tmp.
      PrivateTmp = true;
      Restart = "on-failure";
      RestartSec = 5;

      IPAddressAllow = "localhost";
      IPAddressDeny = "any";
      NoNewPrivileges = true;
      ProtectSystem = "strict";
      ProtectHome = true;
      PrivateDevices = true;
      RestrictSUIDSGID = true;
      LockPersonality = true;
    };
  };

  aiBox.state.paths."/var/lib/private/bambu-studio-api" = {
    backup = "ephemeral";
    why = "orca-slicer-api's data dir and Bambu Studio's app config (StateDirectory of a DynamicUser service): Bambuddy sends every preset with the slice, so nothing here needs keeping.";
  };
}
