# Declarative Hermes cron jobs, in one of two modes:
#
#   aiBox.hermesCron.<name> = {        # monitor mode
#     schedule = "every 5m";
#     monitorScript = ./monitor.py;  # cheap source; its output must be stable
#     prompt = "...";                # run by the cron model only when output changes
#   };
#
#   aiBox.hermesCron.<name> = {        # no-agent mode: the script is the whole job
#     schedule = "every 1m";
#     script = ./job.sh;             # run with bash; stdout is delivered, empty is silent
#   };
#
# The script is installed into HERMES_HOME/scripts (cron requires that), and a
# oneshot creates the job or updates it in place, so jobs live in nix-config
# instead of only in jobs.json.
{
  config,
  lib,
  pkgs,
  ...
}:
let
  hermes = config.services.hermes-agent;
  hermesBin = "${hermes.package}/bin/hermes";
  jobs = config.aiBox.hermesCron;
  noAgent = job: job.script != null;
  # The file a job's script is installed as. Hermes picks the interpreter by
  # extension: .sh runs with bash, anything else with Hermes's own Python.
  scriptName = name: job: if noAgent job then "${name}.sh" else "${name}-monitor.py";
  # The `hermes cron create/edit` flags of the job's mode, prompt aside, e.g.
  # [ "--no-agent" "--script" "notice-relay.sh" ].
  modeArgs =
    name: job:
    if noAgent job then
      [
        "--no-agent"
        "--script"
        (scriptName name job)
      ]
    else
      [
        "--monitor-script"
        (scriptName name job)
        "--model"
        job.model
        "--provider"
        job.provider
      ];
  # The prompt as `cron edit` takes it (a flag) and as `cron create` does (positional, after the
  # schedule); a no-agent job has none.
  promptFlag =
    job:
    lib.optionals (job.prompt != null) [
      "--prompt"
      job.prompt
    ];
  promptArg = job: lib.optional (job.prompt != null) job.prompt;
in
{
  options.aiBox.hermesCron = lib.mkOption {
    default = { };
    description = "Hermes cron jobs in monitor or no-agent mode, declared in nix-config.";
    type = lib.types.attrsOf (
      lib.types.submodule {
        options = {
          schedule = lib.mkOption { type = lib.types.str; };
          monitorScript = lib.mkOption {
            type = lib.types.nullOr lib.types.path;
            default = null;
            description = "Monitor mode: the cheap source script (Python), set together with `prompt`.";
          };
          prompt = lib.mkOption {
            type = lib.types.nullOr lib.types.str;
            default = null;
            description = "Monitor mode: what the cron model does when the monitor's output changes.";
          };
          script = lib.mkOption {
            type = lib.types.nullOr lib.types.path;
            default = null;
            description = "No-agent mode: a shell script that is the whole job, run with bash and no model. Its stdout is delivered verbatim (empty: nothing), and a non-zero exit is reported as the job's failure.";
          };
          deliver = lib.mkOption {
            type = lib.types.str;
            default = "discord";
          };
          model = lib.mkOption {
            type = lib.types.str;
            default = "";
            description = "Pin the job to this model; empty follows cron.model (the local model).";
          };
          provider = lib.mkOption {
            type = lib.types.str;
            default = "";
            description = "The provider paired with `model`.";
          };
        };
      }
    );
  };

  config = lib.mkIf (jobs != { }) {
    assertions = lib.mapAttrsToList (name: job: {
      assertion =
        if noAgent job then
          job.monitorScript == null && job.prompt == null
        else
          job.monitorScript != null && job.prompt != null;
      message = "aiBox.hermesCron.${name}: set either `script` (no-agent mode) or both `monitorScript` and `prompt` (monitor mode).";
    }) jobs;

    services.hermes-agent.hermesHomeFiles = lib.mapAttrs' (
      name: job:
      lib.nameValuePair "scripts/${scriptName name job}" (
        if noAgent job then job.script else job.monitorScript
      )
    ) jobs;

    systemd.services = lib.mapAttrs' (
      name: job:
      lib.nameValuePair "hermes-cron-${name}" {
        description = "Declare the ${name} Hermes cron job";
        after = [ "hermes-agent.service" ];
        wantedBy = [ "multi-user.target" ];
        restartTriggers = [ (builtins.toJSON job) ];
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
          id=$(jq -r '.jobs[]? | select(.name == "${name}") | .id' \
            "$HERMES_HOME/cron/jobs.json" 2>/dev/null || true)
          args=(${lib.escapeShellArgs (modeArgs name job)} --deliver ${job.deliver})
          if [ -n "$id" ]; then
            ${hermesBin} cron edit "$id" --schedule ${lib.escapeShellArg job.schedule} \
              ${lib.escapeShellArgs (promptFlag job)} "''${args[@]}"
          else
            ${hermesBin} cron create --name ${name} "''${args[@]}" \
              ${lib.escapeShellArgs ([ job.schedule ] ++ promptArg job)}
          fi
        '';
      }
    ) jobs;
  };
}
