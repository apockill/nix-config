# agentsview (github.com/kenn-io/agentsview): one place to browse, search and see the cost of
# every agent conversation on ai-box: Claude Code (cc jobs, Sculpt builders, card workers),
# Antigravity CLI, and Hermes itself (Discord, cron, kanban workers, subagents), which it reads
# straight from Hermes's state.db. Served at agentsview.alexthiele.io, behind Cloudflare Access
# like every *.alexthiele.io name.
#
# It runs as hermes because Hermes's state.db is 0600, but it sees only the transcript
# directories, read-only: the rest of /var/lib/hermes is an empty read-only tmpfs, the
# credential files inside ~/.hermes are hidden, and telemetry and the update check are off
# (its only outbound requests are public model-price lists). Its own archive, a SQLite index
# of everything it has read, is /var/lib/agentsview.
{
  config,
  lib,
  pkgs,
  ...
}:
let
  agentsview = pkgs.callPackage ./package.nix { };
  port = 8095;
  address = "agentsview.alexthiele.io";
  dataDir = "/var/lib/agentsview";
  hermesHome = "/var/lib/hermes";

  # Transcript roots, read-only inside the unit.
  claudeProjects = "${hermesHome}/.claude/projects";
  hermesDir = "${hermesHome}/.hermes"; # state.db (+ -wal, -shm) and sessions/
  antigravityDir = "${hermesHome}/.gemini/antigravity-cli";

  # Settings agentsview reads from its config.toml, which it also writes to itself (it
  # generates auth_token and cursor_secret there, and the UI saves its preferences). On every
  # start these keys are set to the values below and everything else in the file is kept.
  settings = {
    local_machine_name = "ai-box";
    # Minimum time between watcher-triggered syncs while the UI is open (default 5s). Every
    # Hermes state.db write makes 0.47.0 re-check all Hermes sessions (~1.5 s of CPU), and
    # Hermes writes it every few seconds; 15 s keeps that to ~10% of a core while someone is
    # looking. With no client for 10 min (sync_idle_after) sync pauses altogether.
    sync_interval = "15s";
  };
  settingsToml = lib.concatStringsSep "\n" (
    lib.mapAttrsToList (k: v: "${k} = ${builtins.toJSON v}") settings
  );
  writeConfig = pkgs.writeShellScript "agentsview-config" ''
    set -euo pipefail
    cfg=${dataDir}/config.toml
    touch "$cfg"
    {
      cat <<'EOF'
    ${settingsToml}
    EOF
      grep -Ev '^(${lib.concatStringsSep "|" (lib.attrNames settings)})[[:space:]]*=' "$cfg" || true
    } > "$cfg.new"
    mv "$cfg.new" "$cfg"
  '';
in
{
  systemd.services.agentsview = {
    description = "agentsview: browse and search every agent conversation on ai-box";
    documentation = [ "https://agentsview.io/docs/" ];
    wantedBy = [ "multi-user.target" ];
    after = [ "local-fs.target" ];
    unitConfig.RequiresMountsFor = [
      hermesHome
      dataDir
    ];

    environment = {
      HOME = dataDir;
      AGENTSVIEW_DATA_DIR = dataDir;
      CLAUDE_PROJECTS_DIR = claudeProjects;
      HERMES_SESSIONS_DIR = "${hermesDir}/sessions";
      ANTIGRAVITY_CLI_DIR = antigravityDir;
      AGENTSVIEW_TELEMETRY_ENABLED = "0";
      DO_NOT_TRACK = "1";
      TZ = config.time.timeZone;
    };

    serviceConfig = {
      Type = "simple";
      User = "hermes";
      Group = "hermes";
      StateDirectory = "agentsview";
      StateDirectoryMode = "0700";
      WorkingDirectory = dataDir;
      UMask = "0077";

      ExecStartPre = writeConfig;
      ExecStart = lib.escapeShellArgs [
        (lib.getExe agentsview)
        "serve"
        "--host"
        "127.0.0.1"
        "--port"
        (toString port)
        "--public-url"
        "https://${address}"
        "--no-browser"
        "--no-update-check"
      ];
      Restart = "on-failure";
      RestartSec = 5;

      # Read-only, and only the transcripts. A missing root (no Antigravity sign-in yet) is
      # skipped; agentsview logs a warning and picks it up after a restart.
      ProtectSystem = "strict";
      ProtectHome = true;
      TemporaryFileSystem = "${hermesHome}:ro";
      BindReadOnlyPaths = [
        "-${claudeProjects}"
        "-${hermesDir}"
        "-${antigravityDir}"
      ];
      InaccessiblePaths = [
        "-${hermesDir}/.env"
        "-${hermesDir}/.anthropic_oauth.json"
        "-${hermesDir}/auth.json"
        "-${hermesDir}/vault"
        "-${hermesDir}/platforms"
        "-/etc/hermes"
        "-/run/hermes-secrets"
      ];
      PrivateTmp = true;
      PrivateDevices = true;
      NoNewPrivileges = true;
      ProtectKernelTunables = true;
      ProtectKernelModules = true;
      ProtectKernelLogs = true;
      ProtectControlGroups = true;
      ProtectClock = true;
      ProtectHostname = true;
      RestrictNamespaces = true;
      RestrictRealtime = true;
      RestrictSUIDSGID = true;
      LockPersonality = true;
      SystemCallArchitectures = "native";
      # Outbound: only the public pricing catalogs (raw.githubusercontent.com, openrouter.ai)
      # at start and daily. Not blocked: the pricing built into 0.47.0 predates
      # claude-opus-5-5 and roughly doubles its cost (cache reads at 0.1x, not 0.05x).
      RestrictAddressFamilies = [
        "AF_UNIX"
        "AF_INET"
        "AF_INET6"
        "AF_NETLINK"
      ];

      # A background viewer: it yields to llama-server and the apps.
      Nice = 10;
      CPUWeight = 20;
      IOWeight = 20;
      MemoryHigh = "1G";
      MemoryMax = "2G";
    };
  };

  # A host block wins over the sites catch-all (./sites/caddy.nix) for this one name.
  services.caddy.virtualHosts."http://${address}".extraConfig = ''
    reverse_proxy 127.0.0.1:${toString port}
  '';

  aiBox.state.paths.${dataDir} = {
    backup = "cache";
    why = "agentsview's index of the agent transcripts (Claude Code, Antigravity, Hermes); rebuilt from them on a new box, like ~/.claude itself.";
  };
}
