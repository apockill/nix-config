# Coding cards on the agent runner: `agent kanban-lane` (agents/runner/agent_runner/kanban_lane.py)
# works each kanban card assigned to `coder` as a runner job and waits on it without a model.
#
# Standard Hermes, used as documented:
#   - the board and its dispatcher: it starts no worker for a `coder` card (`skipped_nonspawnable`);
#     runs, taking back a claim that ran out (a failure booked), notify-subscribe
#   - the `hermes kanban` CLI: list, claim, show, context, heartbeat, comment, complete, block
# Homegrown:
#   - card-lane, a user service beside the runner's: `agent kanban-lane`
#   - aiBox.agents.cardLane.agent: the agent for coder cards
#   - the check: kanban_lane.py's tests, the last of them on Hermes's own board (the dispatcher's
#     tick included), so a Hermes release that changes what the lane relies on fails the build
{
  config,
  lib,
  ...
}:
let
  cfg = config.services.hermes-agent;
  lane = config.aiBox.agents.cardLane;
  runner = config.aiBox.agents.runner.package;
  hermes = "${cfg.package}/bin/hermes";

  command = [
    (lib.getExe runner)
    "kanban-lane"
    "--hermes"
    hermes
    "--agent"
    lane.agent
  ];

  check = runner.overridePythonAttrs {
    pname = "card-lane-check";
    checkPhase = ''
      AGENT_RUNNER_HERMES=${hermes} pytest -q -p no:cacheprovider tests/test_kanban_lane.py
    '';
  };
in
{
  options.aiBox.agents.cardLane = {
    agent = lib.mkOption {
      type = lib.types.enum [
        "claude"
        "antigravity"
      ];
      default = config.aiBox.defaultProvider;
      defaultText = lib.literalExpression "config.aiBox.defaultProvider";
      description = "The agent that works coder cards (the chat keeps aiBox.defaultProvider).";
    };
  };

  config = {
    home-manager.users.${cfg.user}.systemd.user.services.card-lane = {
      Unit = {
        Description = "Kanban cards assigned to coder, worked on the agent runner";
        Wants = [ "agent-runner.service" ];
        After = [ "agent-runner.service" ];
      };
      Service = {
        ExecStart = lib.escapeShellArgs command;
        Environment = [
          # The jobs it starts get its PATH, as they would a terminal's.
          "PATH=/run/wrappers/bin:/etc/profiles/per-user/${cfg.user}/bin:/run/current-system/sw/bin"
          "HERMES_HOME=${cfg.stateDir}/.hermes"
        ];
        # A restart takes back the cards still running; their sessions run on in the runner.
        Restart = "always";
        RestartSec = 10;
      };
      Install.WantedBy = [ "default.target" ];
    };
    system.checks = [ check ];
  };
}
