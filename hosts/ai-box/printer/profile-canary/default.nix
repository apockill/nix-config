# The profile canary: reports what Bambu's newer BBL profiles would change in our slices, and
# switches nothing. ../profiles pins the package the Bambu Studio app installs today; when Bambu
# publishes a newer one, a person's app takes it and our slicer doesn't.
#
# 1. Daily (and ten minutes after a deploy that changes the pin or the canary),
#    bambu-profile-canary.service runs canary.py as the agent user: it asks Bambu's update
#    endpoint the app's question (endpoint.py). Only when the answer is newer than the pin, and
#    once per version, it downloads the package into /var/lib/bambu-profile-canary/<version>/,
#    pre-merges it with ../profiles/premerge.py and the slicer's own defaults, and slices
#    cases.json's two cases with the pinned tree and with the new one, through a private
#    orca-slicer-api on canarySlicerPort (the slicer service's binaries). It writes summary.txt.
# 2. aiBox.hermesCron.bambu-profile-canary runs monitor.py, which only reads summary.txt; the
#    cron model messages Alex when it changes.
# Two layers, like state-audit: the collector needs the network, the slicer and minutes of CPU,
# while a cron monitor script runs inside Hermes's cron, briefly.
{
  config,
  lib,
  pkgs,
  ...
}:
let
  cfg = config.aiBox.printer;
  hermes = config.services.hermes-agent;
  stateDir = "/var/lib/bambu-profile-canary";
  # The slicer service's own packages (../slicer.nix calls the same files: the same derivations).
  profiles = pkgs.callPackage ../profiles { };
  orca-slicer-api = pkgs.callPackage ../orca-slicer-api.nix { };
  python = pkgs.python3.withPackages (ps: [ ps.requests ]);
  # canary.py with its modules, cases and vendored models; the tests run in the build.
  src = lib.fileset.toSource {
    root = ./.;
    fileset = lib.fileset.unions [
      (lib.fileset.fileFilter (f: f.hasExt "py") ./.)
      ./cases.json
      ./models
    ];
  };
  canary =
    pkgs.runCommand "bambu-profile-canary"
      {
        nativeBuildInputs = [
          (pkgs.python3.withPackages (ps: [
            ps.pytest
            ps.requests
          ]))
        ];
      }
      ''
        cp -r ${src} tests && chmod -R u+w tests
        (cd tests && python3 -m pytest -q -p no:cacheprovider)
        mkdir -p $out
        cp -r ${src}/. $out/
      '';
in
{
  options.aiBox.printer.canarySlicerPort = lib.mkOption {
    type = lib.types.port;
    default = 3002;
    internal = true;
    description = "The loopback port of the profile canary's private orca-slicer-api.";
  };

  config = {
    systemd.services.bambu-profile-canary = {
      description = "Report what Bambu's newer BBL profiles would change in our slices";
      after = [ "network-online.target" ];
      wants = [ "network-online.target" ];
      # mkfifo, for the CLI's progress pipe (as in ../slicer.nix).
      path = [ pkgs.coreutils ];
      serviceConfig = {
        Type = "oneshot";
        User = hermes.user;
        Group = hermes.group;
        StateDirectory = "bambu-profile-canary";
        # The cron monitor reads summary.txt as the agent user, and anyone may read the reports.
        StateDirectoryMode = "0755";
        UMask = "0022";
        ExecStart = lib.escapeShellArgs [
          "${python}/bin/python3"
          "${canary}/canary.py"
          "--state"
          stateDir
          "--pinned-tree"
          "${profiles}"
          "--app-version"
          pkgs.bambu-studio.version
          "--cases"
          "${canary}/cases.json"
          "--models"
          "${canary}/models"
          "--orca-slicer-api"
          (lib.getExe orca-slicer-api)
          "--bambu-studio"
          (lib.getExe pkgs.bambu-studio)
          "--premerge"
          "${../profiles/premerge.py}"
          "--defaults"
          "${profiles}/bambu-studio-defaults.json"
          "--preset-cpp"
          "${profiles.presetSources}/Preset.cpp"
          "--print-config-cpp"
          "${profiles.presetSources}/PrintConfig.cpp"
          "--port"
          (toString cfg.canarySlicerPort)
        ];
        # Four slices of small models: a few minutes; an hour means something hangs.
        TimeoutStartSec = "1h";
        Nice = 19;
        IOSchedulingClass = "idle";
        # The CLI uses every core it's given; leave most of the box to the rest.
        CPUQuota = "400%";
        # Its temporary files (packages, slices, orca-slicer-api's work) go here and are removed.
        PrivateTmp = true;
        ProtectSystem = "strict";
        ProtectHome = true;
        NoNewPrivileges = true;
        PrivateDevices = true;
      };
    };
    systemd.timers.bambu-profile-canary = {
      wantedBy = [ "timers.target" ];
      restartTriggers = [
        profiles
        canary
      ];
      timerConfig = {
        OnCalendar = "daily";
        RandomizedDelaySec = "1h";
        Persistent = true;
        OnActiveSec = "10min";
      };
    };

    aiBox.state.paths.${stateDir} = {
      backup = "cache";
      why = "The profile canary's downloads of Bambu's newer BBL profile packages and its reports on them: fetched again and remade if lost.";
    };

    aiBox.hermesCron.bambu-profile-canary = {
      schedule = "every 6h";
      monitorScript = ./monitor.py;
      prompt = ''
        You watch Bambu's slicer profiles for the X2D printer on ai-box (Alex's home server).
        The monitor block is the profile canary's summary: whether Bambu offers the Bambu
        Studio app BBL profiles newer than the ones our slicer service pins, and if so how two
        test slices change with them. Nothing is ever switched by it.
        - If it starts with OK, or says the same as before: respond with [SILENT].
        - If it starts with NEW: a short Discord message for Alex, under 150 words: the new
          version and the pinned one; per case, the time and filament change and the most
          telling changed lines (G-code lines in backticks, as given). Then: adopting them is
          a nix-config change (pin the package in hosts/ai-box/printer/profiles/default.nix)
          plus regenerating the golden slices in ai-box-apps.
        - If it starts with PROBLEM: one line with the problem; the canary retries daily.
        End with: "Reply here and I'll sort it out."
      '';
    };
  };
}
