# Home profile used on every host: shell/dev tooling that doesn't need a GUI.
{
  config,
  pkgs,
  lib,
  ...
}:
{
  imports = [
    ./git.nix
    ./claude.nix
  ];

  programs.home-manager.enable = true;
  programs.direnv = {
    enable = true;
    nix-direnv.enable = true;
  };
  nixpkgs.config.allowUnfree = true;
}
