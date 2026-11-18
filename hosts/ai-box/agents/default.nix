# The coding agents on ai-box: Claude Code and the Antigravity CLI, on the subscriptions Alex pays
# for. Each vendor has one directory holding everything specific to it (packages, settings,
# permissions, auth, models, hooks); everything outside them talks about "the agent".
#   claude/       Claude Code (Anthropic)
#   antigravity/  the Antigravity CLI, agy (Google)
#   AGENTS.md     machine-wide instructions for every agent session
#
# Shared by every vendor, in ~/.agents (vendors link their own file names to these):
#   AGENTS.md  ./AGENTS.md, installed like Hermes's own instructions (hermes/default.nix): only
#              when the repo's version changes, so an edit on disk lasts until then
#   skills/    user-level skills, one folder each with a SKILL.md, written for any agent
#
# Decisions and evidence: the agent's workspace designs/agent-agnostic.md and
# designs/agent-agnostic-spike.md.
{ config, lib, ... }:
let
  cfg = config.services.hermes-agent;
  shared = "${cfg.stateDir}/.agents";

  package =
    description:
    lib.mkOption {
      type = lib.types.package;
      internal = true;
      inherit description;
    };
in
{
  imports = [
    ./claude
    ./antigravity
  ];

  options.aiBox.agents = {
    claude.cli = package "The claude CLI on the agent's PATH.";
    claude.acp = package "claude-agent-acp: Claude Code as an ACP server.";
    antigravity.cli = package "The Antigravity CLI (agy) on the agent's PATH; `agy acp` is its ACP server.";

    instructions = lib.mkOption {
      type = lib.types.str;
      readOnly = true;
      default = "${shared}/AGENTS.md";
      description = "The machine-wide AGENTS.md every agent reads.";
    };
    skills = lib.mkOption {
      type = lib.types.str;
      readOnly = true;
      default = "${shared}/skills";
      description = "The user-level skills folder every agent reads.";
    };
    links = lib.mkOption {
      type = lib.types.attrsOf lib.types.str;
      default = { };
      description = ''
        A vendor's own file name for a shared file or folder: link (absolute path) -> target.
        A real folder already at the link (from before) has its entries moved into the target
        first; anything of the same name already in the target stays, and the folder is kept.
      '';
    };
  };

  config = {
    aiBox.state.paths.${shared} = {
      backup = "cache";
      why = "Shared agent config (hosts/ai-box/agents): AGENTS.md, reinstalled from the repo when missing, and the user-level skills folder, whose entries are links to checkouts (spec init) or generated.";
    };

    # Folders kept across boots are bind mounts (state/persist.nix); a link made before its folder
    # is mounted (the first switch that declares it) would be hidden under the mount.
    systemd.services."home-manager-${cfg.user}".unitConfig.RequiresMountsFor = [
      shared
    ]
    ++ lib.attrNames config.aiBox.agents.links;

    home-manager.users.${cfg.user} =
      { lib, ... }:
      {
        home.activation.agentLinks = lib.hm.dag.entryAfter [ "writeBoundary" ] ''
          run mkdir -p ${config.aiBox.agents.skills}
          agentLink() {
            local link=$1 target=$2 entry
            if [ -L "$link" ]; then
              run ln -sfn "$target" "$link"
            elif [ -d "$link" ]; then
              for entry in "$link"/* "$link"/.[!.]*; do
                [ -e "$entry" ] || [ -L "$entry" ] || continue
                if [ -e "$target/''${entry##*/}" ] || [ -L "$target/''${entry##*/}" ]; then
                  echo "agentLink: kept $entry: $target has one of that name" >&2
                else
                  run mv "$entry" "$target/"
                fi
              done
              run rmdir "$link" && run ln -s "$target" "$link" \
                || echo "agentLink: $link isn't empty, so it isn't linked to $target" >&2
            else
              [ -e "$link" ] && run rm "$link"
              run mkdir -p "''${link%/*}"
              run ln -s "$target" "$link"
            fi
          }
          ${lib.concatStrings (
            lib.mapAttrsToList (link: target: ''
              agentLink ${lib.escapeShellArg link} ${lib.escapeShellArg target}
            '') config.aiBox.agents.links
          )}
        '';
      };
  };
}
