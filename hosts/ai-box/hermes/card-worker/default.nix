# Coding cards on the agent runner: a kanban card assigned to `coder` is worked by
# `agent kanban-worker` (agents/runner/agent_runner/hermes_board.py), not by a Hermes agent
# babysitting a job. Hermes's dispatcher still claims it, heartbeats, reclaims, retries and
# notifies; the job is a runner session (card-<id>) on aiBox.agents.cardWorker's agent, with
# vendor defaults; nothing runs a model just to watch it. Every other card is Hermes's as before.
#
# All of the Hermes coupling is here and in hermes_board.py:
#   ./plugin.py, ./plugin.yaml     the plugin (installed as its __init__.py): gives a coder card
#                                  our command (command.json)
#   ./contract.py                  the system build's check that Hermes still honours that seam
#   profiles/coder/.env            an empty profile, so the dispatcher counts `coder` as spawnable.
#                                  Only the empty .env: a profile with a config would turn the
#                                  gateway into a multi-profile host (credentials scoped per profile)
#                                  for a profile that never runs a Hermes agent.
# Only the gateway's dispatcher loads plugins: a hand-run `hermes kanban dispatch` gives a coder
# card a Hermes worker, so leave dispatching to the gateway.
{
  config,
  lib,
  pkgs,
  ...
}:
let
  cfg = config.services.hermes-agent;
  hermesHome = "${cfg.stateDir}/.hermes";
  worker = config.aiBox.agents.cardWorker;

  # What a coder card's worker runs. Hermes pins its own source tree on PYTHONPATH and points
  # HERMES_HOME at the (empty) coder profile; the bridge's `hermes kanban` calls want the board's.
  command = [
    "${pkgs.coreutils}/bin/env"
    "-u"
    "PYTHONPATH"
    "HERMES_HOME=${hermesHome}"
    (lib.getExe config.aiBox.agents.runner.package)
    "kanban-worker"
    "--hermes"
    "${cfg.package}/bin/hermes"
    "--agent"
    worker.agent
  ]
  ++ lib.optionals (worker.model != null) [
    "--model"
    worker.model
  ];

  plugin = pkgs.runCommand "hermes-card-worker" { } ''
    mkdir $out
    cp ${./plugin.py} $out/__init__.py
    cp ${./plugin.yaml} $out/plugin.yaml
    echo ${lib.escapeShellArg (builtins.toJSON command)} > $out/command.json
  '';

  # The contract check's stand-in for the bridge: it records the environment it was given.
  stub = pkgs.writeShellScript "card-worker-stub" ''
    ${lib.getExe pkgs.jq} -n env > "$HERMES_HOME/recorded.tmp" && mv "$HERMES_HOME/recorded.tmp" "$HERMES_HOME/recorded.json"
  '';
  contract = pkgs.runCommand "hermes-card-worker-contract" { } ''
    export HOME=$TMPDIR HERMES_HOME=$TMPDIR/hermes
    ${cfg.package.hermesVenv}/bin/python3 ${./contract.py} ${plugin} ${stub} \
      ${cfg.package}/bin/hermes ${../../agents/runner/agent_runner/hermes_board.py}
    touch $out
  '';
in
{
  options.aiBox.agents.cardWorker = {
    agent = lib.mkOption {
      type = lib.types.enum [
        "claude"
        "antigravity"
      ];
      default = config.aiBox.defaultProvider;
      defaultText = lib.literalExpression "config.aiBox.defaultProvider";
      description = "The agent that works coder cards (the chat keeps aiBox.defaultProvider).";
    };
    model = lib.mkOption {
      type = lib.types.nullOr lib.types.str;
      default = null;
      description = "The model for coder cards; null keeps the agent's own default.";
    };
  };

  config = {
    services.hermes-agent.settings.plugins.enabled = [ "card-worker" ];
    aiBox.agents.links."${hermesHome}/plugins/card-worker" = "${plugin}";
    systemd.services.hermes-agent.restartTriggers = [ plugin ];
    systemd.tmpfiles.settings.card-worker = {
      "${hermesHome}/profiles/coder".d = {
        inherit (cfg) user group;
        mode = "0700";
      };
      "${hermesHome}/profiles/coder/.env".f = {
        inherit (cfg) user group;
        mode = "0600";
      };
    };
    system.checks = [ contract ];
  };
}
