# Off-box backups: restic to the agent's Google Drive (ai-box/backups/restic),
# via rclone. What's backed up is generated from the `restic` entries in
# aiBox.state.paths (../state/paths.nix), minus nested paths declared with
# another class. Paths with a `*` segment are expanded at backup time.
#
# Credentials live in 1Password (vault ai-assistant), fetched into RAM at boot:
# - "Backups (ai-box)": restic password, rclone's Drive token, folder id.
# - "Google Cloud": the OAuth client rclone signs in with.
#
# Backups read from a read-only btrfs snapshot of /, so databases are copied
# at one frozen moment. In the repository, paths therefore start with
# /.snapshots/restic-source (e.g. /.snapshots/restic-source/var/lib/hermes/...).
#
# Restore (any machine with restic + rclone and the two 1Password items):
#   restic -r rclone:gdrive:backups/restic snapshots
#   restic -r rclone:gdrive:backups/restic restore latest --target /tmp/restore
{
  config,
  lib,
  pkgs,
  ...
}:
let
  name = "gdrive";
  repository = "rclone:gdrive:backups/restic";
  secretsDir = "/run/backup-secrets";
  statusDir = "/var/lib/backup-status";
  snapshot = "/.snapshots/restic-source"; # on snapper's subvolume, not the root
  btrfs = "${pkgs.btrfs-progs}/bin/btrfs";
  # The 1Password service-account token (see hosts/ai-box/hermes).
  serviceAccountEnv = "/etc/hermes/op-service-account.env";

  # 1Password item ids: "Backups (ai-box)" and "Google Cloud".
  backupsItem = "op://ai-assistant/x2fbtrq6tirvl2lhvutf37bdle";
  gcloudItem = "op://ai-assistant/kt754v7xmovuckfvxoysrocd3i";
  rcloneTemplate = pkgs.writeText "rclone.conf.tpl" ''
    [gdrive]
    type = drive
    scope = drive
    client_id = {{ ${gcloudItem}/rclone/client_id }}
    client_secret = {{ ${gcloudItem}/rclone/client_secret }}
    root_folder_id = {{ ${backupsItem}/rclone/root_folder_id }}
    token = {{ ${backupsItem}/rclone/rclone_token }}
  '';

  # Paths to back up, and nested paths of other classes to leave out.
  declared = config.aiBox.state.paths;
  resticPaths = lib.attrNames (lib.filterAttrs (_: p: p.backup == "restic") declared);
  # Is `path` strictly inside `parent`? A `*` segment on either side matches
  # any name, so a pattern counts as inside whatever its matches would be in.
  isInside =
    parent: path:
    let
      parentSegments = lib.splitString "/" parent;
      pathSegments = lib.splitString "/" path;
    in
    lib.length pathSegments > lib.length parentSegments
    && lib.all (pair: pair.fst == pair.snd || pair.fst == "*" || pair.snd == "*") (
      lib.zipLists parentSegments pathSegments
    );
  excluded = lib.filter (
    path: declared.${path}.backup != "restic" && lib.any (r: isInside r path) resticPaths
  ) (lib.attrNames declared);
  inSnapshot = path: "${snapshot}${path}";
  # `path` as a shell word: each segment quoted, except `*` segments, which
  # the shell expands. Exact paths come out as one literal word.
  shellWord =
    path:
    "/"
    + lib.concatMapStringsSep "/" (
      segment: if segment == "*" then "*" else lib.escapeShellArg segment
    ) (lib.tail (lib.splitString "/" path));

  # Files whose restore the weekly drill checks.
  drillFiles = [
    "/var/lib/hermes/.hermes/state.db"
    "/var/lib/hermes/sites/markets/state/markets.db"
  ];
  drillDir = "/var/tmp/restic-drill";
  restic = "${pkgs.restic}/bin/restic";
in
{
  # Fetch the credentials into RAM before backups run.
  systemd.services.backup-secrets = {
    description = "Fetch backup credentials from 1Password";
    wants = [ "network-online.target" ];
    after = [ "network-online.target" ];
    unitConfig.ConditionPathExists = serviceAccountEnv;
    path = [ pkgs._1password-cli ];
    # op needs a writable config dir and a system service has no $HOME.
    environment.OP_CONFIG_DIR = "${secretsDir}/op";
    serviceConfig = {
      Type = "oneshot";
      RemainAfterExit = true;
      EnvironmentFile = serviceAccountEnv;
      RuntimeDirectory = "backup-secrets";
      RuntimeDirectoryMode = "0700";
      UMask = "0077";
    };
    script = ''
      mkdir -p "$OP_CONFIG_DIR"
      # The network can be up before DNS/TLS to 1Password works; retry briefly.
      for attempt in 1 2 3 4 5 6; do
        if op inject --force --in-file ${rcloneTemplate} --out-file ${secretsDir}/rclone.conf &&
          op read --out-file ${secretsDir}/restic-password --force "${backupsItem}/password"; then
          exit 0
        fi
        sleep 10
      done
      exit 1
    '';
  };

  services.restic.backups.${name} = {
    inherit repository;
    passwordFile = "${secretsDir}/restic-password";
    rcloneConfigFile = "${secretsDir}/rclone.conf";
    initialize = true;
    # Generated at backup time so SQLite's -wal/-shm files (recent writes) are
    # included next to declared databases, but only when they exist, and so
    # `*` segments expand to what's in the snapshot (nullglob: a pattern with
    # no matches lists nothing; dotglob: `*` matches any name, as in the audit).
    dynamicFilesFrom = ''
      shopt -s nullglob dotglob
      for path in ${lib.concatMapStringsSep " " (p: shellWord (inSnapshot p)) resticPaths}; do
        echo "$path"
        for sidecar in "$path-wal" "$path-shm"; do
          if [ -e "$sidecar" ]; then echo "$sidecar"; fi
        done
      done
    '';
    exclude = map inSnapshot excluded;
    backupPrepareCommand = ''
      ${btrfs} subvolume delete ${snapshot} 2>/dev/null || true
      ${btrfs} subvolume snapshot -r / ${snapshot}
    '';
    backupCleanupCommand = ''
      ${btrfs} subvolume delete ${snapshot}
    '';
    pruneOpts = [
      "--keep-daily 7"
      "--keep-weekly 4"
      "--keep-monthly 6"
    ];
    timerConfig = {
      OnCalendar = "03:30";
      RandomizedDelaySec = "30m";
      Persistent = true; # catch up after downtime
    };
  };

  systemd.services."restic-backups-${name}" = {
    requires = [ "backup-secrets.service" ];
    after = [ "backup-secrets.service" ];
    serviceConfig = {
      StateDirectory = "backup-status";
      StateDirectoryMode = "0755";
      # Runs only if the backup and prune succeeded; read by ./monitor.py.
      ExecStartPost = pkgs.writeShellScript "mark-backup-success" ''
        ${pkgs.coreutils}/bin/date +%s > ${statusDir}/last-backup
      '';
    };
  };

  # Weekly restore drill: verify the repository, restore the newest snapshot
  # of a few key files to a scratch dir, and check they're intact.
  systemd.services.restic-restore-drill = {
    description = "Restore drill for the ${name} restic backups";
    requires = [ "backup-secrets.service" ];
    after = [
      "backup-secrets.service"
      "restic-backups-${name}.service"
    ];
    path = [ pkgs.rclone ];
    environment = {
      RESTIC_REPOSITORY = repository;
      RESTIC_PASSWORD_FILE = "${secretsDir}/restic-password";
      RCLONE_CONFIG = "${secretsDir}/rclone.conf";
      RESTIC_CACHE_DIR = "/var/cache/restic-restore-drill";
    };
    serviceConfig = {
      Type = "oneshot";
      StateDirectory = "backup-status";
      CacheDirectory = "restic-restore-drill";
      Nice = 19;
      IOSchedulingClass = "idle";
    };
    script = ''
      rm -rf ${drillDir}
      trap 'rm -rf ${drillDir}' EXIT
      ${restic} check
      ${restic} restore latest --target ${drillDir} ${
        lib.concatMapStringsSep " " (f: "--include ${inSnapshot f}") drillFiles
      }
      ${lib.concatMapStringsSep "\n" (f: ''
        test -s ${drillDir}${inSnapshot f}
        [ "$(${pkgs.sqlite}/bin/sqlite3 ${drillDir}${inSnapshot f} 'PRAGMA integrity_check')" = ok ]
      '') drillFiles}
      date +%s > ${statusDir}/last-drill
    '';
  };
  systemd.timers.restic-restore-drill = {
    wantedBy = [ "timers.target" ];
    timerConfig = {
      OnCalendar = "Sun 05:00";
      Persistent = true;
    };
  };

  aiBox.hermesCron.backups = {
    schedule = "every 6h";
    monitorScript = ./monitor.py;
    prompt = ''
      You watch ai-box's off-box backups (restic to Google Drive). If the
      monitor output is OK, respond with [SILENT]. Otherwise write a short
      Discord message for Alex (under 80 words): what's wrong, in plain words
      (backup failing, backup overdue, or the weekly restore drill failing or
      overdue), and that the logs are in `journalctl -u restic-backups-gdrive`
      or `-u restic-restore-drill`. A common cause is Google revoking the
      Drive login; then the fix is re-running rclone's sign-in. End with:
      "Reply here and I'll look into it."
    '';
  };

  aiBox.state.paths.${statusDir} = {
    backup = "host";
    why = "When this box last backed up and passed a restore drill (read by the backup alert).";
  };
}
