# Apps supervisor + health alerts for the web apps in /var/lib/hermes/sites.
#
#   runner.py   launches every app with an executable start.sh, health-checks
#               it over app.sock, restarts it with backoff, gives up after a
#               cap, and records everything in /var/lib/apps-health (the
#               portal status page reads it).
#   monitor.py  cheap Hermes cron "monitor" source: the local cron model only
#               runs when its output changes, i.e. when an app needs Alex.
#
# Removing this directory (and its import) removes the whole feature.
{
  config,
  pkgs,
  ...
}:
let
  hermes = config.services.hermes-agent;
  hermesBin = "${hermes.package}/bin/hermes";

  cronName = "apps-health";
  cronSchedule = "every 5m";
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

  # Monitor source for the cron job (cron scripts must live in HERMES_HOME/scripts).
  services.hermes-agent.hermesHomeFiles."scripts/apps-health-monitor.py" = ./monitor.py;

  # Keep the cron job declared here: create it, or update it in place.
  systemd.services.hermes-cron-apps-health = {
    description = "Declare the apps-health Hermes cron job";
    after = [ "hermes-agent.service" ];
    wantedBy = [ "multi-user.target" ];
    restartTriggers = [ cronPrompt ];
    path = [ pkgs.jq ];
    environment = {
      HERMES_HOME = "${hermes.stateDir}/.hermes";
      HOME = hermes.stateDir;
    };
    serviceConfig = {
      Type = "oneshot";
      RemainAfterExit = true;
      User = hermes.user;
      Group = hermes.group;
    };
    script = ''
      id=$(jq -r '.jobs[]? | select(.name == "${cronName}") | .id' \
        "$HERMES_HOME/cron/jobs.json" 2>/dev/null || true)
      args=(--monitor-script apps-health-monitor.py --deliver discord)
      if [ -n "$id" ]; then
        ${hermesBin} cron edit "$id" --schedule "${cronSchedule}" \
          --prompt ${pkgs.lib.escapeShellArg cronPrompt} "''${args[@]}"
      else
        ${hermesBin} cron create --name ${cronName} "''${args[@]}" \
          "${cronSchedule}" ${pkgs.lib.escapeShellArg cronPrompt}
      fi
    '';
  };
}
