# `cc`: the agent's Claude Code jobs as Remote Control sessions, so Alex can
# watch and steer them from claude.ai/code or the Claude app while they run.
#
# Each job is an interactive `claude --remote-control` in its own tmux session.
# Remote Control needs the full `claude auth login` (stored in
# ~/.claude/.credentials.json); the long-lived CLAUDE_CODE_OAUTH_TOKEN can't
# open Remote Control sessions and takes precedence, so jobs run without it.
# Plain `claude -p` keeps using the token, as the fallback when the login lapses.
#
# The tmux server runs as its own service (cc-tmux), not under the agent: a
# gateway restart (every switch, including the hourly upgrade) killed jobs
# whose tmux lived in hermes-agent's cgroup. A switch doesn't restart it either.
{ config, lib, pkgs, ... }:
let
  cfg = config.services.hermes-agent;
  sock = "/run/cc-tmux/sock";
  tmuxCmd = "${pkgs.tmux}/bin/tmux -S ${sock}";

  cc = pkgs.writeShellApplication {
    name = "cc";
    runtimeInputs = with pkgs; [
      tmux
      jq
      coreutils
      gnugrep
      gnused
    ];
    runtimeEnv.CC_TMUX_SOCK = sock;
    text = builtins.readFile ./cc.sh;
  };
in
{
  services.hermes-agent.extraPackages = [ cc ];

  systemd.services.cc-tmux = {
    description = "tmux server for the agent's Claude Code jobs (cc)";
    wantedBy = [ "multi-user.target" ];
    after = [ "network-online.target" ];
    wants = [ "network-online.target" ];
    # Updating the unit must not end running jobs; the new one applies on the next start.
    restartIfChanged = false;
    environment = {
      HOME = cfg.stateDir;
      PATH = lib.mkForce "/run/wrappers/bin:/etc/profiles/per-user/${cfg.user}/bin:/run/current-system/sw/bin";
    };
    serviceConfig = {
      User = cfg.user;
      Group = cfg.group;
      Type = "forking";
      RuntimeDirectory = "cc-tmux";
      RuntimeDirectoryMode = "0700";
      WorkingDirectory = cfg.stateDir;
      # A placeholder session keeps the server up with no jobs.
      ExecStart = "${tmuxCmd} new-session -d -s _keep ${pkgs.coreutils}/bin/sleep infinity";
      ExecStop = "${tmuxCmd} kill-server";
      Restart = "on-failure";
    };
  };
}
