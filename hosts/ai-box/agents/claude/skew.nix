# The version skew check: claude-agent-acp bundles the Claude Agent SDK built for one Claude Code
# release, but runs the claude of ./claude-code.nix, which the claude-code-nix input moves on every
# lock update. A mismatch fails the system build, at PR time, rather than sessions at run time. It
# is a build-time check only: it reads two package.json files and runs no agent.
{ config, pkgs, ... }:
let
  inherit (config.aiBox.agents.claude) acp cli;
  sdk = "${acp}/lib/node_modules/@agentclientprotocol/claude-agent-acp/node_modules/@anthropic-ai/claude-agent-sdk/package.json";
in
{
  system.checks = [
    (pkgs.runCommand "claude-agent-acp-skew-check" { nativeBuildInputs = [ pkgs.jq ]; } ''
      for_cli=$(jq -r .claudeCodeVersion ${sdk})
      if [ "$for_cli" != ${cli.version} ]; then
        echo "claude-agent-acp ${acp.version} bundles the Claude Agent SDK for Claude Code $for_cli," \
          "but the CLI is ${cli.version}: bump agents/claude/acp.nix (or hold the claude-code-nix input back)" >&2
        exit 1
      fi
      touch $out
    '')
  ];
}
