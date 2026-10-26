# Declarative Hermes cron jobs.
#
#   aiBox.hermesCron.<name> = {
#     schedule = "every 5m";
#     monitorScript = ./monitor.py;  # optional: cheap source; output must be stable,
#                                    # the model runs only when it changes
#     prompt = "...";
#     toolsets = [ "terminal" ];     # optional: this job's tools, instead of
#                                    # platform_toolsets.cron (web, vision, ...)
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
  hermesPython = "${hermes.package.passthru.hermesVenv}/bin/python3";
  jobs = config.aiBox.hermesCron;
  scriptName = name: "${name}-monitor.py";
in
{
  options.aiBox.hermesCron = lib.mkOption {
    default = { };
    description = "Hermes cron jobs, declared in nix-config.";
    type = lib.types.attrsOf (
      lib.types.submodule {
        options = {
          schedule = lib.mkOption { type = lib.types.str; };
          monitorScript = lib.mkOption {
            type = lib.types.nullOr lib.types.path;
            default = null;
          };
          toolsets = lib.mkOption {
            type = lib.types.nullOr (lib.types.listOf lib.types.str);
            default = null;
          };
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
    ) (lib.filterAttrs (_: job: job.monitorScript != null) jobs);

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
          args=(${
            lib.optionalString (job.monitorScript != null) "--monitor-script ${scriptName name}"
          } --deliver ${job.deliver})
          if [ -n "$id" ]; then
            ${hermesBin} cron edit "$id" --schedule ${lib.escapeShellArg job.schedule} \
              --prompt ${lib.escapeShellArg job.prompt} "''${args[@]}"
          else
            ${hermesBin} cron create --name ${name} "''${args[@]}" \
              ${lib.escapeShellArg job.schedule} ${lib.escapeShellArg job.prompt}
          fi
          # The CLI can't set per-job toolsets; Hermes' own API can (under its lock).
          ${hermesPython} -c 'import json, sys; from cron.jobs import list_jobs, update_job
          j = [j for j in list_jobs(True) if j["name"] == sys.argv[1]][0]
          update_job(j["id"], {"enabled_toolsets": json.loads(sys.argv[2])})' \
            ${name} ${lib.escapeShellArg (builtins.toJSON job.toolsets)}
        '';
      }
    ) jobs;
  };
}
