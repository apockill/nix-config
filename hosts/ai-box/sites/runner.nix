# Apps supervisor + health alerts for the web apps in /var/lib/hermes/sites.
#
#   runner.py   launches every app with an executable start.sh, health-checks
#               it over app.sock, restarts it with backoff, gives up after a
#               cap, and records everything in /var/lib/apps-health (the
#               portal status page reads it).
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
  # After a power cut ai-box boots with its clock at 1970 until NTP sets it, and the
  # runner's uptime history then gets 1970 timestamps (seen on the 2026-10-18 and -20 boots).
  # Start it once the clock is synchronized; give up waiting after 5 min (no network).
  systemd.additionalUpstreamSystemUnits = [ "systemd-time-wait-sync.service" ];
  systemd.services.systemd-time-wait-sync = {
    wantedBy = [ "sysinit.target" ];
    serviceConfig.TimeoutStartSec = "5min";
  };

  systemd.services.ai-box-apps-runner = {
    description = "Supervisor and health recorder for ai-box web apps";
    after = [
      "network.target"
      "time-sync.target"
    ];
    wants = [ "time-sync.target" ];
    wantedBy = [ "multi-user.target" ];
    path = [
      pkgs.bash
      pkgs.nix
      pkgs.git
      pkgs.coreutils
      pkgs.procps
    ];
    environment.PYTHONUNBUFFERED = "1";
    serviceConfig = {
      User = "hermes";
      Group = "hermes";
      WorkingDirectory = "/var/lib/hermes/sites";
      ExecStart = "${pkgs.python3}/bin/python3 ${./runner.py}";
      StateDirectory = "apps-health";
      StateDirectoryMode = "0755";
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
