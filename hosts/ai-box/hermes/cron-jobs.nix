# Declarative Hermes cron jobs in "monitor" mode.
#
#   aiBox.hermesCron.<name> = {
#     schedule = "every 5m";
#     monitorScript = ./monitor.py;  # cheap source; its output must be stable
#     prompt = "...";                # run by the cron model only when output changes
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
  scriptName = name: "${name}-monitor.py";
in
{
  options.aiBox.hermesCron = lib.mkOption {
    default = { };
    description = "Hermes cron jobs in monitor mode, declared in nix-config.";
    type = lib.types.attrsOf (
      lib.types.submodule {
        options = {
          schedule = lib.mkOption { type = lib.types.str; };
          monitorScript = lib.mkOption { type = lib.types.path; };
          prompt = lib.mkOption { type = lib.types.str; };
          deliver = lib.mkOption {
            type = lib.types.str;
            default = "discord";
          };
        };
      }
    );
  };

  config = lib.mkIf (jobs != { }) {
    services.hermes-agent.hermesHomeFiles = lib.mapAttrs' (
      name: job: lib.nameValuePair "scripts/${scriptName name}" job.monitorScript
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
          args=(--monitor-script ${scriptName name} --deliver ${job.deliver})
          if [ -n "$id" ]; then
            ${hermesBin} cron edit "$id" --schedule ${lib.escapeShellArg job.schedule} \
              --prompt ${lib.escapeShellArg job.prompt} "''${args[@]}"
          else
            ${hermesBin} cron create --name ${name} "''${args[@]}" \
              ${lib.escapeShellArg job.schedule} ${lib.escapeShellArg job.prompt}
          fi
        '';
      }
    ) jobs;
  };
}
