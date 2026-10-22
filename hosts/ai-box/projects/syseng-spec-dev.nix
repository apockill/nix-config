# The syseng spec toolkit (github.com/apockill/syseng-spec-dev): Alex iterates
# on it, and the agent dogfoods it on other projects.
#
# - The clone in /var/lib/hermes/projects is the one copy: it's made on
#   activation if missing, and never touched after that (no pulls, no resets).
# - `spec` runs that checkout's source, so a toolkit change is live everywhere
#   at once, with no install or upgrade step. Agents and the toolkit's Claude
#   Code hooks run `spec` from the PATH on most tool calls, so it's plain
#   Python rather than a Nix build per call.
# - The skill and subagents: `spec init` links them from ~/.claude to this
#   checkout, so they're live too.
{ config, pkgs, ... }:
let
  cfg = config.services.hermes-agent;
  dir = "${cfg.stateDir}/projects/syseng-spec-dev";
  repo = "github.com/apockill/syseng-spec-dev";

  # The toolkit's [project] dependencies in its pyproject.toml. A new
  # dependency there needs adding here too.
  python = pkgs.python3.withPackages (ps: [
    ps.pyyaml
    ps.pydantic
  ]);

  spec = pkgs.writeShellScriptBin "spec" ''
    if [ ! -d ${dir}/src/syseng ]; then
      echo "spec: no toolkit checkout at ${dir}" >&2
      exit 1
    fi
    PYTHONPATH="${dir}/src''${PYTHONPATH:+:$PYTHONPATH}" exec ${python}/bin/python3 -m syseng "$@"
  '';
in
{
  aiBox.state.paths.${dir} = {
    backup = "git";
    inherit repo;
    why = "The agent's clone of the syseng spec toolkit; spec runs it (projects/syseng-spec-dev.nix).";
  };

  home-manager.users.${cfg.user} =
    { lib, ... }:
    {
      home.packages = [ spec ];

      # Clone once if missing. Not fatal: with no network at boot the next
      # activation (switch or boot) tries again.
      home.activation.sysengSpecDevClone = lib.hm.dag.entryAfter [ "writeBoundary" ] ''
        if [ ! -e ${dir}/.git ]; then
          run mkdir -p ${dir}
          run ${pkgs.git}/bin/git clone https://${repo}.git ${dir} \
            || echo "syseng-spec-dev: clone failed; retried on the next activation" >&2
        fi
      '';
    };
}
