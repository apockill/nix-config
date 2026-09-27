{
  config,
  pkgs,
  lib,
  ...
}:
{
  imports = [
    ./dconf.nix
    ./git.nix
    ./gnome_extensions.nix
    ./chrome.nix
    ./vscode.nix
    ./antigravity.nix
    ./claude.nix
  ];

  programs.home-manager.enable = true;
  programs.direnv = {
    enable = true;
    nix-direnv.enable = true;
  };
  nixpkgs.config.allowUnfree = true;

  home.stateVersion = "24.11";
}
