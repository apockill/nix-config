{ inputs, pkgs, ... }:
let
  system = pkgs.stdenv.hostPlatform.system;
  antigravityPkgs = inputs.antigravity-nix.packages.${system};
in
{
  home.packages = [
    # Antigravity 2.0 Agent Manager
    antigravityPkgs.google-antigravity-no-fhs

    # Antigravity IDE
    antigravityPkgs.google-antigravity-ide-no-fhs

    # Antigravity CLI
    antigravityPkgs.google-antigravity-cli
  ];
}
