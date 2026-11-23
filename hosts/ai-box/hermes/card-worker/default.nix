# Coding cards on the agent runner: a kanban card assigned to `coder` is worked by
# `agent kanban-worker` instead of a Hermes agent babysitting a job, with no model watching it.
#
# Standard Hermes, used as documented:
#   - the board and its dispatcher: claims, heartbeats, reclaim, retries, the block after 2
#     failures, notify
#   - the plugin system: ~/.hermes/plugins, plugin.yaml, register(ctx), plugins.enabled
#   - profiles as assignees
#   - the `hermes kanban` CLI and the worker's env vars (HERMES_KANBAN_*)
#   - the worker exit codes, 75 (rate-limited) included
# Homegrown:
#   - ./plugin.py: replaces the private kanban_db_dispatch._worker_argv for coder cards only. The
#     one unsupported seam, until NousResearch/hermes-agent#146543 (plugin worker lanes) lands.
#   - the empty coder profile (profiles/coder/.env only): spawnable, but no second servable
#     profile, which would turn the gateway into a multi-profile host
#   - agents/runner/agent_runner/hermes_board.py: `agent kanban-worker`, the bridge
#   - aiBox.agents.cardWorker: the agent and model for coder cards
#   - ./contract.py: the build's check that Hermes still honours the seam (plus mypy --strict
#     and ruff on this folder)
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
