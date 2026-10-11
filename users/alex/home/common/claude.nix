{ inputs, pkgs, ... }:
let
  system = pkgs.stdenv.hostPlatform.system;
in
{
  home.packages = [
    inputs.claude-code-nix.packages.${system}.default
  ];
}
