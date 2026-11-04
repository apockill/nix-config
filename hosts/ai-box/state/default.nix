# Explicit state. The root filesystem is wiped on every boot; the paths in
# aiBox.state.paths (./paths.nix) are the only state that survives, each with
# an answer to "how is it backed up?".
#
# How the wipe works (./persist.nix): kept paths live on the @persist subvolume,
# mounted at /persist, and impermanence bind-mounts each one to its real path.
# Early in every boot the initrd moves the old root, @root, to
# old_roots/<timestamp> on the btrfs top level and creates an empty @root.
# Only the outermost kept paths get a bind mount; anything declared inside one
# (a cache folder in a restic folder) lives on @persist with it. For the same
# reason an ephemeral path can't sit inside a kept one (the build fails): it
# would be kept, not wiped. Declare such files `cache` to keep them out of
# backups.
#
# Each boot prunes old roots retired more than 30 days ago, then retires the
# current one, so the previous boot's root is always there. To get a file back:
#   sudo mount -o subvolid=5 /dev/disk/by-partlabel/disk-nvme-root /mnt
#   ls /mnt/old_roots/   # one per boot, named by when its / last changed
#   sudo cp -a /mnt/old_roots/<timestamp>/etc/foo /etc/foo; sudo umount /mnt
#
# Undeclared state is caught three ways: the build fails on incomplete
# declarations, an hourly audit (./audit.py) reports undeclared paths to Alex
# through the local cron model, and ai-box-reboot refuses to run while any
# exist.
#
# Backup classes:
#   git        the repo (`repo`) is the source of truth. Uncommitted files
#              inside are disposable (rebuilding from the repo is the intended
#              recovery); declare any that matter separately. The audit lists
#              them as a non-blocking note, so we can keep an eye on them.
#   restic     backed up off-box with restic
#   cache      kept to avoid rebuilding or re-downloading; never backed up
#   host       belongs to this machine (identity, its own history). Kept, never
#              backed up: a new box starts with its own. Treated like cache for
#              now; may be handled differently later.
#   manual     re-provisioned by a human on a new box (e.g. the vault token)
#   ephemeral  NOT kept: fine to lose on every boot
#
# A nested path with a different class overrides its parent (e.g. a cache
# folder inside a restic folder is excluded from backups).
#
# A path segment may be `*`, matching any one directory name, so a feature can
# declare one path for many directories: "/var/lib/hermes/sites/*/state" is
# every web app's state. No other glob syntax is allowed. A `*` path must sit
# inside a kept path, which carries it to /persist.
#
# Kept files (not directories) need `file = true`: impermanence bind-mounts
# files and directories differently.
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
    "host"
    "manual"
    "ephemeral"
  ];
  declaredJson = pkgs.writeText "state-declared.json" (
    builtins.toJSON (
      lib.mapAttrs (_: p: {
        inherit (p) backup why watch;
        repo = p.repo;
      }) cfg.paths
    )
  );
  auditDir = "/var/lib/state-audit";
  python = "${pkgs.python3}/bin/python3";
in
{
  imports = [
    ./paths.nix
    ./users.nix
    ./persist.nix
    ./migrate-persist.nix
  ];

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
            watch = lib.mkOption {
              type = lib.types.bool;
              default = false;
              description = "List files written here at runtime (non-blocking), to spot config worth declaring.";
            };
            file = lib.mkOption {
              type = lib.types.bool;
              default = false;
              description = "The path is a file, not a directory (needed for kept paths; see ./persist.nix).";
            };
          };
        }
      );
    };

    checkCommand = lib.mkOption {
      type = lib.types.str;
      readOnly = true;
      default = "env PATH=${pkgs.git}/bin:$PATH ${python} ${./audit.py} check ${declaredJson}";
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
          assertion = lib.all (
            segment:
            segment == "*"
            || !(lib.any (c: lib.hasInfix c segment) [
              "*"
              "?"
              "["
            ])
          ) (lib.splitString "/" path);
          message = "aiBox.state.paths.\"${path}\": a segment may be exactly `*` (any one name); no other `*`, `?` or `[`.";
        }
        {
          assertion = lib.stringLength (lib.trim p.why) > 0;
          message = "aiBox.state.paths.\"${path}\": `why` is required (what is this, and why this backup class?).";
        }
        {
          assertion = (p.backup == "git") == (p.repo != null);
          message = "aiBox.state.paths.\"${path}\": `repo` is required for backup = \"git\" and only allowed there.";
        }
        {
          assertion = !p.file || !(lib.any (other: lib.hasPrefix "${path}/" other) (lib.attrNames cfg.paths));
          message = "aiBox.state.paths.\"${path}\": has `file = true` but other paths are declared inside it.";
        }
      ]) cfg.paths
    );

    # Two layers, on purpose:
    # - This root service does the walk and writes summary.txt. It has to be
    #   root: as hermes it can't see /root, NetworkManager's connections or
    #   /var/lib/private, which is exactly where undeclared state hides.
    #   ai-box-reboot runs the same audit directly, with no Hermes involved.
    # - The hermesCron job below only reads summary.txt (cron monitor scripts
    #   run as hermes) and wakes the cron model when it changes.
    # aiBox.hermesCron could grow a `collector` option that generates this
    # service and timer; not worth it until a second job needs a timed root
    # collector (apps-health's collector is a long-running supervisor).
    systemd.services.state-audit = {
      description = "Audit root filesystem for undeclared state";
      path = [ pkgs.git ]; # lists uncommitted files in `git` paths
      serviceConfig = {
        Type = "oneshot";
        StateDirectory = "state-audit";
        StateDirectoryMode = "0755";
        UMask = "0022";
        Nice = 19;
        IOSchedulingClass = "idle";
        ExecStart = "${python} ${./audit.py} report ${declaredJson} ${auditDir}";
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
        declare. The root is wiped on boot, so these are deleted on the next
        reboot. Write a short Discord message for Alex, under 120 words:
        - For each newly listed path: the path, and in a few words what it
          probably is (guess only from the path). Say it is deleted on the next
          reboot and needs a decision: keep it with a backup class (git, restic,
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
