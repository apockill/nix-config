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
    # Never start on a state root that isn't the persistent one (../state/paths.nix): on a
    # boot where the mount fails, the runner would make empty state directories on the wiped
    # root and start every instance on them (ai-box-apps STATE-3).
    unitConfig.RequiresMountsFor = [ "/var/lib/hermes/instances" ];
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
      # Where LAUNCH-8 reads a secret a parameter references (ai-box-apps D5, open): nothing
      # renders this directory yet, and no app declares a secret; hermes-secrets renders one
      # root-owned env file. Rendering sites/<name> for group hermes comes with D5's answer.
      SITES_SECRETS_DIR = "/run/hermes-secrets/sites";
    };
    serviceConfig = {
      User = "hermes";
      Group = "hermes";
      WorkingDirectory = "/var/lib/hermes/sites";
      ExecStart = "/var/lib/hermes/sites/tools/runner/run serve";
      StateDirectory = "apps-health";
      StateDirectoryMode = "0755";
      # /run/sites: each instance's runtime directory and socket; Caddy reads it. Preserved
      # across restarts of the unit (a crash, a switch): it holds each instance's .runner.failed
      # marker, which keeps a failed instance failed until re-armed (LAUNCH-15), and its app.log.
      RuntimeDirectory = "sites";
      RuntimeDirectoryMode = "0755";
      RuntimeDirectoryPreserve = "yes";
      # Zenoh's shared memory for camera frames is mlocked; 8 MiB is too little.
      LimitMEMLOCK = "infinity";
      # On stop, systemd signals the runner alone (KillMode mixed: SIGTERM to the main process,
      # SIGKILL to the rest only at the timeout), so the runner's orderly stop runs: it asks
      # process-compose to stop the project, which stops the instances with their 10 s grace
      # (sequentially at worst: 11 instances), then waits up to 60 s for process-compose.
      KillMode = "mixed";
      TimeoutStopSec = "200s";
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
