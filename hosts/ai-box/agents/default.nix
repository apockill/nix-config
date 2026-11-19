# The coding agents on ai-box: Claude Code and the Antigravity CLI, on the subscriptions Alex pays
# for. Each vendor has one directory holding everything specific to it (packages, settings,
# permissions, auth, models, hooks); everything outside them talks about "the agent".
#   claude/       Claude Code (Anthropic)
#   antigravity/  the Antigravity CLI, agy (Google)
#   runner/       the agent runner: every session over ACP, with a local API (runner/README.md)
#   drift/        the drift guards: agents-canary and agents-usage-digest (daily), and the
#                 version skew check is claude/skew.nix
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
  inherit (config.aiBox.agents) links;

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
    ./runner
    ./drift
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
      description = "A vendor's own file name for a shared file or folder: link (absolute, in the agent's home) -> target. home-manager makes each link.";
    };
  };

  config = {
    aiBox.state.paths.${shared} = {
      backup = "cache";
      why = "Shared agent config (hosts/ai-box/agents): AGENTS.md, reinstalled from the repo when missing, and the user-level skills folder, whose entries are links to checkouts (spec init) or generated.";
    };

    # The shared skills folder, which the vendors' skills links point to.
    systemd.tmpfiles.settings.agents.${config.aiBox.agents.skills}.d = {
      inherit (cfg) user group;
      mode = "0755";
    };

    # Folders kept across boots are bind mounts (state/persist.nix); a link made before its folder
    # is mounted (the first switch that declares it) would be hidden under the mount.
    systemd.services."home-manager-${cfg.user}".unitConfig.RequiresMountsFor = [
      shared
    ]
    ++ lib.attrNames config.aiBox.agents.links;

    assertions = lib.mapAttrsToList (link: _: {
      assertion = lib.hasPrefix "${cfg.stateDir}/" link;
      message = "aiBox.agents.links: ${link} isn't in the agent's home (${cfg.stateDir})";
    }) config.aiBox.agents.links;

    home-manager.users.${cfg.user} =
      { config, ... }:
      {
        home.file = lib.mapAttrs' (
          link: target:
          lib.nameValuePair (lib.removePrefix "${cfg.stateDir}/" link) {
            source = config.lib.file.mkOutOfStoreSymlink target;
          }
        ) links;
      };
  };
}
