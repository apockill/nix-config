# Antigravity (Google): everything specific to the Antigravity CLI (agy) on ai-box.
{
  config,
  inputs,
  pkgs,
  ...
}:
let
  # The package alex's desktop uses (users/alex/home/desktop/antigravity.nix), from the
  # antigravity-nix flake, but at 1.5.10 instead of the input's 1.5.9: over ACP, 1.5.9 drops what
  # agy says after a turn has ended (a subagent's result arriving), which 1.5.10 streams (both
  # tested on ai-box, 2026-11-17). Drop the override once the input has 1.5.10 or later.
  cli =
    inputs.antigravity-nix.packages.${pkgs.stdenv.hostPlatform.system}.google-antigravity-cli.overrideAttrs
      {
        version = "1.5.10-5253791805734912";
        src = pkgs.fetchurl {
          url = "https://storage.googleapis.com/antigravity-public/antigravity-cli/1.5.10-5253791805734912/linux-arm/cli_linux_arm64.tar.gz";
          sha512 = "f9f5c7ebc47a8b8de536acca8116b1f5a43dca614cde94008fe5a510517b23535fb281d85416930d76e76478858bf3dc66ea6d1b0c9b6eeadcfabe4d8ef2a807";
        };
      };

  # agy updates itself unless told not to: in the read-only store that only fails and logs, and
  # versions come from here anyway.
  agy = pkgs.symlinkJoin {
    name = "agy";
    paths = [ cli ];
    nativeBuildInputs = [ pkgs.makeWrapper ];
    postBuild = "wrapProgram $out/bin/agy --set AGY_CLI_DISABLE_AUTO_UPDATE 1";
  };
in
{
  aiBox.agents.antigravity.cli = agy;
  services.hermes-agent.extraPackages = [ agy ];
}
