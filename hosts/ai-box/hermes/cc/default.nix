# `cc`: the agent's coding jobs, as sessions on the agent runner (../../agents/runner).
#
# `cc start <title> <dir> <task-file>` starts a job as a runner session named after its title:
# Claude Code by default, the Antigravity CLI with `--agent antigravity`. `cc send/peek/answer/
# list/stop` follow and steer it. Jobs run in the runner's service, so gateway restarts and
# switches leave them running, and a reboot leaves them resumable (the next `cc send` resumes the
# conversation). ./cc.py is the CLI (stdlib Python; tests in ./test_cc.py, run by `just test`).
#
# Before the runner, each job was an interactive `claude --remote-control` in tmux, so Alex could
# follow it in the Claude app; the sites live view replaces that. The jobs started that way run on
# until they finish: the cc-tmux service and its tool, `cc-tmux` (./cc_tmux.py, the old cc), stay
# for them, `cc` hands it any job name only that tmux server knows, and cc-restore still resumes
# them at boot. Both go once the last of them has ended.
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

  cc = pkgs.writers.writePython3Bin "cc" {
    # W503: black breaks long conditions before the operator.
    flakeIgnore = [
      "E501"
      "W503"
    ];
    makeWrapperArgs = [
      "--set-default"
      "CC_RUNNER"
      "${config.aiBox.agents.runner.package}/bin/agent-runner"
      "--set-default"
      "CC_LEGACY"
      "${ccTmux}/bin/cc-tmux"
    ];
  } (builtins.readFile ./cc.py);
in
{
  services.hermes-agent.extraPackages = [
    cc
    ccTmux
  ];

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
