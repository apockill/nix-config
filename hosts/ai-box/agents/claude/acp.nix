# claude-agent-acp: Claude Code as an Agent Client Protocol (ACP) server, so the agent runner
# (../runner) drives Claude the same way it drives Antigravity. It's the Claude Agent SDK over the
# same claude binary as the agent's own CLI (CLAUDE_CODE_EXECUTABLE), with Claude Code's system
# prompt, tools and settings; the deltas from the interactive CLI are in the spike's findings
# (workspace designs/agent-agnostic-spike.md).
#
# nixpkgs has it (unstable: 0.100.0), but this is the release the spike verified, built the same
# way (nixpkgs' pkgs/by-name/cl/claude-agent-acp). To update: bump `version`, set both hashes to
# lib.fakeHash, build, and copy the hashes nix reports.
{
  lib,
  buildNpmPackage,
  fetchFromGitHub,
  makeWrapper,
  claude,
}:
buildNpmPackage (finalAttrs: {
  pname = "claude-agent-acp";
  version = "0.109.1";

  src = fetchFromGitHub {
    owner = "agentclientprotocol";
    repo = "claude-agent-acp";
    tag = "v${finalAttrs.version}";
    hash = "sha256-1nX95rqpzbbPk5OFcpVJLfewemIX3GW7BhYXP9oZboE=";
  };

  npmDepsHash = "sha256-yz+zSb0XRVowNbRU9qvNsi0Wsc+cTZ2Iqlg+vqCuA2c=";

  nativeBuildInputs = [ makeWrapper ];

  # The SDK's own bundled claude is a generic-Linux binary that NixOS can't run (354 MB): the
  # adapter starts the agent's claude instead, so there's one Claude Code build for every route.
  postInstall = ''
    rm -r $out/lib/node_modules/@agentclientprotocol/claude-agent-acp/node_modules/@anthropic-ai/claude-agent-sdk-linux-*
    wrapProgram $out/bin/claude-agent-acp \
      --set-default CLAUDE_CODE_EXECUTABLE ${claude}/bin/claude
  '';

  meta = {
    description = "ACP-compatible coding agent powered by the Claude Agent SDK";
    homepage = "https://github.com/agentclientprotocol/claude-agent-acp";
    license = lib.licenses.asl20;
    mainProgram = "claude-agent-acp";
  };
})
