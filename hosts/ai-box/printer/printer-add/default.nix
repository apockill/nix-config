# Adds the X2D to Bambuddy (../bambuddy.nix), so the printer is declared here rather than
# entered in Bambuddy's UI. add_printer.py creates it through Bambuddy's API when no
# printer with its serial number exists, and leaves an existing one alone (renamed or
# reconfigured in the UI, it stays as it is).
#
# The access code (the printer's LAN password for MQTT, FTPS and the camera) comes from
# 1Password through the agent's secrets file. Bambuddy logs into the printer before it
# saves it, so while the printer is off the unit fails and systemd tries again.
{ config, pkgs, ... }:
let
  cfg = config.aiBox.printer;
  add-printer = pkgs.writers.writePython3Bin "bambuddy-add-printer" {
    # E501 and W503 clash with black's formatting.
    flakeIgnore = [
      "E501"
      "W503"
    ];
  } (builtins.readFile ./add_printer.py);
in
{
  # "Bambu LAN Mode Settings"; its password field is the access code.
  aiBox.hermesSecrets = ''
    # Bambu X2D LAN access code (hosts/ai-box/printer/printer-add)
    BAMBU_X2D_ACCESS_CODE={{ op://ai-assistant/tdecu3s5ihyjpnnst3fvhqjaxa/password }}
  '';

  systemd.services.bambuddy-add-printer = {
    description = "Add the X2D to Bambuddy";
    wantedBy = [ "multi-user.target" ];
    wants = [
      "bambuddy.service"
      "hermes-secrets.service"
    ];
    after = [
      "bambuddy.service"
      "hermes-secrets.service"
    ];
    # Retry every 5 minutes, without systemd's start limit, while the printer is off.
    startLimitIntervalSec = 0;
    serviceConfig = {
      Type = "oneshot";
      RemainAfterExit = true;
      Restart = "on-failure";
      RestartSec = "5min";
      DynamicUser = true;
      EnvironmentFile = "/run/hermes-secrets/env";
      ExecStart = builtins.concatStringsSep " " [
        "${add-printer}/bin/bambuddy-add-printer"
        "--url http://127.0.0.1:${toString cfg.bambuddyPort}"
        "--name X2D"
        "--model X2D"
        "--ip 192.168.86.54"
        "--serial 20P5AJ662701727"
        "--access-code-env BAMBU_X2D_ACCESS_CODE"
      ];
      IPAddressAllow = "localhost";
      IPAddressDeny = "any";
      NoNewPrivileges = true;
      ProtectSystem = "strict";
      ProtectHome = true;
      PrivateTmp = true;
    };
  };
}
