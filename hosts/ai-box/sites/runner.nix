# Apps supervisor + health alerts for the web apps in /var/lib/hermes/sites.
#
#   ai-box-apps-runner  the one service for the apps: it runs the repo's apps
#               runner (tools/runner/run serve), which reads namespaces/,
#               checks every instance before launch and runs them under
#               process-compose 1.124 from the repo's own flake, healing them as
#               the old runner did and recording status.json and events.jsonl in
#               /var/lib/apps-health (the portal status page reads them).
#               Sockets: /run/sites/<address>/app.sock; state:
#               /var/lib/hermes/instances/<address>/ (../state/paths.nix).
#   monitor.py  cheap Hermes cron "monitor" source: the local cron model only
#               runs when its output changes, i.e. when an app needs Alex.
{ pkgs, ... }:
let
  cronPrompt = ''
    You watch the web apps on ai-box (Alex's home server). The monitor block
    above shows what changed in their health summary. Write a short Discord
    message for Alex, under 120 words:
    - For each newly FAILED app: its name and URL, what went wrong in one or two
      plain sentences based only on the reason and log lines (quote the single
      most telling log line), and that auto-healing gave up. End with: "Reply to
      this message and I'll take a look."
    - If the apps runner heartbeat is stale: say the supervisor is down, so
      nothing is being healed.
    - If the summary went back to OK: one line naming the apps that recovered.
    - If nothing changed that Alex needs to know about: respond with [SILENT].
    Don't guess beyond what the logs show.
  '';
in
{
  systemd.services.ai-box-apps-runner = {
    description = "Supervisor and health recorder for ai-box web apps";
    after = [ "network.target" ];
    wantedBy = [ "multi-user.target" ];
    path = [
      pkgs.bash
      pkgs.nix
      pkgs.git
      pkgs.coreutils
      pkgs.procps
    ];
    environment = {
      PYTHONUNBUFFERED = "1";
      SITES_LIVE_CHECKOUT = "/var/lib/hermes/sites";
      SITES_STATE_ROOT = "/var/lib/hermes/instances";
      SITES_RUNTIME_ROOT = "/run/sites";
      SITES_HEALTH_DIR = "/var/lib/apps-health";
      SITES_SECRETS_DIR = "/run/hermes-secrets/sites";
    };
    serviceConfig = {
      User = "hermes";
      Group = "hermes";
      WorkingDirectory = "/var/lib/hermes/sites";
      ExecStart = "/var/lib/hermes/sites/tools/runner/run serve";
      StateDirectory = "apps-health";
      StateDirectoryMode = "0755";
      # /run/sites: each instance's runtime directory and socket; Caddy reads it.
      RuntimeDirectory = "sites";
      RuntimeDirectoryMode = "0755";
      # Zenoh's shared memory for camera frames is mlocked; 8 MiB is too little.
      LimitMEMLOCK = "infinity";
      # process-compose stops every instance (10 s grace each) before it exits.
      TimeoutStopSec = "90s";
      Restart = "always";
      RestartSec = "5s";
    };
  };

  aiBox.hermesCron.apps-health = {
    schedule = "every 5m";
    monitorScript = ./monitor.py;
    prompt = cronPrompt;
  };
}
