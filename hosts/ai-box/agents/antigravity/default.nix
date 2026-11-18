# Antigravity (Google): everything specific to the Antigravity CLI (agy) on ai-box.
{
  config,
  inputs,
  pkgs,
  ...
}:
let
  # The same package as alex's desktop (users/alex/home/desktop/antigravity.nix), from the
  # antigravity-nix flake. It updates itself unless told not to: in the read-only store that only
  # fails and logs, and versions come from the flake input anyway.
  agy = pkgs.symlinkJoin {
    name = "agy";
    paths = [
      inputs.antigravity-nix.packages.${pkgs.stdenv.hostPlatform.system}.google-antigravity-cli
    ];
    nativeBuildInputs = [ pkgs.makeWrapper ];
    postBuild = "wrapProgram $out/bin/agy --set AGY_CLI_DISABLE_AUTO_UPDATE 1";
  };
in
{
  aiBox.agents.antigravity.cli = agy;
  services.hermes-agent.extraPackages = [ agy ];
}
