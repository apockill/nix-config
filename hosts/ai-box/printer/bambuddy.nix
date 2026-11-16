# Bambuddy (github.com/maziggy/bambuddy): the one thing on the box that talks to the Bambu
# X2D. It holds the printer's MQTT connection, the camera stream (the X2D allows one
# connection, so everything else takes frames from Bambuddy), the print queue, the library
# and the print archive. Agents reach it through the lab-printer node (ai-box-apps), which
# frames its web UI; it is also served at bambuddy.alexthiele.io for that frame, behind
# Cloudflare Access like every *.alexthiele.io name.
#
# Based on claha/smart-home's nixos/modules/bambuddy.nix (MIT, Claes Hallström),
# https://github.com/claha/smart-home/blob/965f972845f74fcff95a87a7ea6c0cc54deb421a/nixos/modules/bambuddy.nix
# trimmed to what ai-box uses: no options, loopback only, logs in /var/log, and the slicer
# and frame settings set here.
{
  config,
  lib,
  pkgs,
  ...
}:
let
  cfg = config.aiBox.printer;
  dataDir = "/var/lib/bambuddy";
in
{
  users.users.bambuddy = {
    isSystemUser = true;
    group = "bambuddy";
    home = dataDir;
    description = "Bambuddy service user";
  };
  users.groups.bambuddy = { };

  systemd.services.bambuddy = {
    description = "Bambuddy, the Bambu Lab printer server";
    documentation = [ "https://wiki.bambuddy.cool/getting-started/installation/" ];
    wantedBy = [ "multi-user.target" ];
    wants = [ "network-online.target" ];
    after = [ "network-online.target" ];

    environment = {
      DATA_DIR = dataDir;
      LOG_DIR = "/var/log/bambuddy";
      TZ = config.time.timeZone;
      # lab-printer's page frames Bambuddy's UI.
      TRUSTED_FRAME_ORIGINS = "https://lab-printer.alexthiele.io";
      # Slicing goes to the native Bambu Studio behind ./slicer.nix. This is the fallback
      # Bambuddy uses while its own "Bambu Studio API URL" setting is empty.
      BAMBU_STUDIO_API_URL = "http://127.0.0.1:${toString cfg.slicerPort}";
    };

    serviceConfig = {
      Type = "simple";
      User = "bambuddy";
      Group = "bambuddy";
      StateDirectory = "bambuddy";
      StateDirectoryMode = "0750";
      LogsDirectory = "bambuddy";
      WorkingDirectory = dataDir;

      # --loop asyncio: uvloop truncates virtual printer FTP uploads on slow
      # storage (#1896).
      # --timeout-graceful-shutdown: uvicorn otherwise waits forever for an
      # in-flight MJPEG camera stream and systemd has to SIGKILL the service,
      # skipping the SQLite WAL checkpoint and the virtual printer teardown.
      ExecStart = lib.escapeShellArgs [
        (lib.getExe pkgs.bambuddy)
        "--host"
        "127.0.0.1"
        "--port"
        (toString cfg.bambuddyPort)
        "--loop"
        "asyncio"
        "--timeout-graceful-shutdown"
        "5"
      ];

      Restart = "on-failure";
      RestartSec = 5;
      TimeoutStopSec = 30;

      # Hardening. The service only needs to write to its own directories.
      NoNewPrivileges = true;
      PrivateTmp = true;
      ProtectSystem = "strict";
      ProtectHome = true;
      RestrictSUIDSGID = true;
      LockPersonality = true;
    };
  };

  # A host block wins over the sites catch-all (../sites/caddy.nix) for this one name.
  services.caddy.virtualHosts."http://bambuddy.alexthiele.io".extraConfig = ''
    reverse_proxy 127.0.0.1:${toString cfg.bambuddyPort}
  '';

  aiBox.state.paths = {
    ${dataDir} = {
      backup = "restic";
      why = "Bambuddy's database (printers, queue, print history, settings, presets), library files and print archive: Alex's print records.";
    };
    "${dataDir}/backups" = {
      backup = "cache";
      why = "Bambuddy's own scheduled backups of the database above; restic already has it.";
    };
    "${dataDir}/firmware" = {
      backup = "cache";
      why = "Printer firmware Bambuddy downloaded; re-downloadable.";
    };
    "${dataDir}/timelapse_frames" = {
      backup = "cache";
      why = "Frames Bambuddy grabs while it builds a timelapse; the finished video goes to the archive.";
    };
  };
}
