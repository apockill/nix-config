# sculpt-launcher: starts and resumes Sculpt Studio's builder sessions (Alex, 11-14: Sculpt Studio's
# builder is an agent session per project, resumed, surviving restarts; the studio's backend
# decides when a project needs its builder, and this service only bridges the app sandbox).
#
# The studio (the lab-sculpt instance, ai-box-apps' apps/sculpt-studio) runs sandboxed under the
# apps runner and can't start an agent. This service runs the studio's own launcher script from
# the live sites checkout as the agent's user: it long-polls `builder-wakes` on the studio's socket,
# asks the agent runner (../../agents/runner, SCULPT_RUNNER) for one session per wanted project in
# the project's directory with the studio's builder environment first on PATH, follows it there and
# reports builder-started/-ended. Everything studio-specific (which project, the prompt, the
# environment, the permission fence, Claude or another agent) comes from the studio and its script.
#
# Builders are runner sessions, so they show in the sites live view (agents.<domain>) as
# "sculpt: <project>", sign in as every runner session does (the runner's subscription token), and
# outlive this service: a restart or a switch doesn't cut a builder off, and the next start follows
# the running sessions again. No fallback: with the runner down or an agent that can't start, the
# project shows its builder paused and why.
#
# `--claude` and CLAUDE_CONFIG_DIR are for a launcher from before the runner (it runs `claude -p`
# itself); the current one ignores them. Drop them once ai-box-apps' change agent-runner is on main.
{
  config,
  lib,
  pkgs,
  ...
}:
let
  cfg = config.services.hermes-agent;
  sites = "${cfg.stateDir}/sites";
in
{
  systemd.services.sculpt-launcher = {
    description = "Sculpt Studio's builder sessions (one agent-runner session per project)";
    wantedBy = [ "multi-user.target" ];
    after = [ "network-online.target" "ai-box-apps-runner.service" ];
    wants = [ "network-online.target" ];
    restartIfChanged = false;
    environment = {
      HOME = cfg.stateDir;
      CLAUDE_CONFIG_DIR = "${cfg.stateDir}/.claude";
      PATH = lib.mkForce "/run/wrappers/bin:/etc/profiles/per-user/${cfg.user}/bin:/run/current-system/sw/bin";
      # The runner's API (agents/runner/README.md); a launcher from before the runner ignores it.
      SCULPT_RUNNER = config.aiBox.agents.runner.socket;
    };
    serviceConfig = {
      User = cfg.user;
      Group = cfg.group;
      WorkingDirectory = cfg.stateDir;
      ExecStart = lib.concatStringsSep " " [
        "${pkgs.python3}/bin/python3"
        "${sites}/apps/sculpt-studio/launcher/launcher.py"
        "--socket /run/sites/lab-sculpt/app.sock"
        "--claude /etc/profiles/per-user/${cfg.user}/bin/claude"
      ];
      # The studio or the runner may be down or restarting (a namespace switch); the script
      # retries, and a crash or a missing script (the checkout on another branch) is retried here.
      Restart = "always";
      RestartSec = 10;
    };
  };
}
