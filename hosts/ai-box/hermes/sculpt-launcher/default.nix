# sculpt-launcher: starts and resumes Sculpt Studio's builder sessions (Alex, 11-14: Sculpt Studio's
# builder is a Claude Code session per project, resumed, surviving restarts; the studio's backend
# decides when a project needs its builder, and this service only bridges the app sandbox).
#
# The studio (the lab-sculpt instance, ai-box-apps' apps/sculpt-studio) runs sandboxed under the
# apps runner and can't start Claude Code. This service runs the studio's own launcher script from
# the live sites checkout as the agent's user: it long-polls `builder-wakes` on the studio's socket,
# runs one `claude -p` per wanted project in the project's directory with the studio's builder
# environment first on PATH, and reports builder-started/-ended. Everything studio-specific (which
# project, the prompt, the environment, the permission fence) comes from the studio and its script.
#
# Builders authenticate with the claude.ai login in ~/.claude (like cc's jobs). A switch doesn't
# restart the service, so running builders aren't cut off mid-turn; a crash restarts it, and the
# studio re-offers any project whose builder didn't report back.
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
    description = "Sculpt Studio's builder sessions (Claude Code, one per project)";
    wantedBy = [ "multi-user.target" ];
    after = [ "network-online.target" ];
    wants = [ "network-online.target" ];
    restartIfChanged = false;
    environment = {
      HOME = cfg.stateDir;
      CLAUDE_CONFIG_DIR = "${cfg.stateDir}/.claude";
      PATH = lib.mkForce "/run/wrappers/bin:/etc/profiles/per-user/${cfg.user}/bin:/run/current-system/sw/bin";
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
      # The studio may be down or restarting (a namespace switch); the script retries, and a crash
      # or a missing script (the checkout on another branch) is retried here.
      Restart = "always";
      RestartSec = 30;
    };
  };
}
