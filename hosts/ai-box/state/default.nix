# Explicit state: every path on the root filesystem that should survive a
# root wipe is declared here with an answer to "how is it backed up?".
#
# Stage 1 (now): declarations, build-time checks, an hourly audit of anything
# undeclared (pinged to Alex via the local cron model), and a gate that stops
# ai-box-reboot while undeclared state exists. Nothing is wiped yet.
# Stage 2: restic backups generated from the `restic` entries.
# Stage 3: wipe root on boot; persist exactly these paths.
#
# Backup classes:
#   git        valuable parts live in a git remote (`repo`); runtime files
#              inside may be declared separately (usually as restic)
#   restic     backed up off-box (stage 2)
#   cache      kept to avoid rebuilding or re-downloading; never backed up
#   manual     re-provisioned by a human on a new box (e.g. the vault token)
#   ephemeral  NOT kept: fine to lose on every boot
#
# A nested path with a different class overrides its parent (e.g. a cache
# folder inside a restic folder is excluded from backups).
{
  config,
  lib,
  pkgs,
  ...
}:
let
  cfg = config.aiBox.state;
  classes = [
    "git"
    "restic"
    "cache"
    "manual"
    "ephemeral"
  ];
  declaredJson = pkgs.writeText "state-declared.json" (
    builtins.toJSON (
      lib.mapAttrs (_: p: {
        inherit (p) backup why;
        repo = p.repo;
      }) cfg.paths
    )
  );
  auditDir = "/var/lib/state-audit";
  python = "${pkgs.python3}/bin/python3";
in
{
  imports = [ ./paths.nix ];

  options.aiBox.state = {
    paths = lib.mkOption {
      default = { };
      description = "Declared state paths, each with a backup class (see state/default.nix).";
      type = lib.types.attrsOf (
        lib.types.submodule {
          options = {
            backup = lib.mkOption { type = lib.types.enum classes; };
            why = lib.mkOption { type = lib.types.str; };
            repo = lib.mkOption {
              type = lib.types.nullOr lib.types.str;
              default = null;
            };
          };
        }
      );
    };

    checkCommand = lib.mkOption {
      type = lib.types.str;
      readOnly = true;
      default = "${python} ${./audit.py} --check ${declaredJson}";
      description = "Exits 1 and lists paths if undeclared state exists (used by ai-box-reboot).";
    };
  };

  config = {
    assertions = lib.flatten (
      lib.mapAttrsToList (path: p: [
        {
          assertion = lib.hasPrefix "/" path && !(lib.hasSuffix "/" path) && path != "/";
          message = "aiBox.state.paths.\"${path}\": must be absolute, not '/', without a trailing slash.";
        }
        {
          assertion = lib.stringLength (lib.trim p.why) > 0;
          message = "aiBox.state.paths.\"${path}\": `why` is required (what is this, and why this backup class?).";
        }
        {
          assertion = (p.backup == "git") == (p.repo != null);
          message = "aiBox.state.paths.\"${path}\": `repo` is required for backup = \"git\" and only allowed there.";
        }
      ]) cfg.paths
    );

    systemd.services.state-audit = {
      description = "Audit root filesystem for undeclared state";
      serviceConfig = {
        Type = "oneshot";
        StateDirectory = "state-audit";
        StateDirectoryMode = "0755";
        UMask = "0022";
        Nice = 19;
        IOSchedulingClass = "idle";
        ExecStart = "${python} ${./audit.py} ${declaredJson} ${auditDir}";
      };
    };
    # Hourly, plus a minute after any deploy that changes the declarations or
    # the audit (the timer restarts then, and OnActiveSec fires).
    systemd.timers.state-audit = {
      wantedBy = [ "timers.target" ];
      restartTriggers = [
        declaredJson
        ./audit.py
      ];
      timerConfig = {
        OnActiveSec = "1min";
        OnBootSec = "10min";
        OnUnitActiveSec = "1h";
      };
    };

    aiBox.hermesCron.state-audit = {
      schedule = "every 30m";
      monitorScript = ./monitor.py;
      prompt = ''
        You watch ai-box (Alex's home server) for undeclared state. The monitor
        block lists paths on the root filesystem that nix-config doesn't
        declare. Once the root is wiped on boot, these would be lost. Write a
        short Discord message for Alex, under 120 words:
        - For each newly listed path: the path, and in a few words what it
          probably is (guess only from the path). Say it would be lost on a root
          wipe and needs a decision: keep it with a backup class (git, restic,
          cache, manual) or mark it ephemeral in hosts/ai-box/state/paths.nix.
        - If paths disappeared from the list (now declared or deleted), one line
          saying so.
        - If the report is stale or missing, say the audit isn't running.
        - If the output is OK and was OK before, respond with [SILENT].
        End with: "Reply here and I'll sort it out."
      '';
    };
  };
}
