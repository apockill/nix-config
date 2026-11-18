# The jobs started in tmux before the agent runner (../../agents/runner), until the last one ends.
#
# Before the runner, each job was an interactive `claude --remote-control` in tmux, so Alex could
# follow it in the Claude app; the runner's sessions and the sites live view replace that. The jobs
# started that way run on until they finish: the cc-tmux service and its tool, `cc-tmux`
# (./cc_tmux.py, the old cc), stay for them, the runner's CLI (`agent`) hands it any job name only
# that tmux server knows (aiBox.agents.runner.tmuxJobs), and cc-restore still resumes them at boot.
#
# `cc` is now only another name for `agent` (`cc start <title> <dir> <task-file>` and the rest work
# as before), kept for the Hermes skills that still say `cc`. All of this directory goes once the
# last tmux job has ended (`agent list` shows them) and the skills say `agent`.
{
  config,
  lib,
  pkgs,
  ...
}:
let
  cfg = config.services.hermes-agent;
  sock = "/run/cc-tmux/sock";
  # Inside ~/.claude (declared state), next to the transcripts the records point to.
  jobs = "${cfg.stateDir}/.claude/cc-jobs";
  tmuxCmd = "${pkgs.tmux}/bin/tmux -S ${sock}";

  # cc_tmux.py reads all three from the environment; a caller's own values win
  # (the tests point them at a scratch server).
  ccTmux = pkgs.writers.writePython3Bin "cc-tmux" {
    flakeIgnore = [ "E501" ];
    makeWrapperArgs = [
      "--set-default"
      "CC_TMUX"
      "${pkgs.tmux}/bin/tmux"
      "--set-default"
      "CC_TMUX_SOCK"
      sock
      "--set-default"
      "CC_JOBS"
      jobs
    ];
  } (builtins.readFile ./cc_tmux.py);

  # `cc`: `agent` under its old name.
  agent = config.aiBox.agents.runner.package;
  cc = pkgs.runCommand "cc" { } ''
    mkdir -p $out/bin
    ln -s ${agent}/bin/agent $out/bin/cc
  '';
in
{
  services.hermes-agent.extraPackages = [
    cc
    ccTmux
  ];
  aiBox.agents.runner.tmuxJobs = "${ccTmux}/bin/cc-tmux";

  systemd.services.cc-tmux = {
    description = "tmux server for the agent's Claude Code jobs from before the agent runner (cc-tmux)";
    wantedBy = [ "multi-user.target" ];
    after = [ "network-online.target" ];
    wants = [ "network-online.target" ];
    # Updating the unit must not end running jobs; the new one applies on the next start.
    restartIfChanged = false;
    environment = {
      HOME = cfg.stateDir;
      # Claude Code's .claude.json lives in ~/.claude, which survives the root
      # wipe as one directory (state/paths.nix); a file of its own in ~ can't
      # be bind-mounted, because Claude Code replaces it by renaming.
      CLAUDE_CONFIG_DIR = "${cfg.stateDir}/.claude";
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

  # Pulled in by every start of cc-tmux (boot, or a restart after a crash took the jobs with it).
  systemd.services.cc-restore = {
    description = "Resume the agent's recorded tmux Claude Code jobs (cc-tmux restore)";
    wantedBy = [ "cc-tmux.service" ];
    after = [ "cc-tmux.service" ];
    environment.HOME = cfg.stateDir;
    serviceConfig = {
      User = cfg.user;
      Group = cfg.group;
      Type = "oneshot";
      ExecStart = "${ccTmux}/bin/cc-tmux restore";
    };
  };
}
