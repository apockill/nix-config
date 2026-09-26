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
  ];

  programs.home-manager.enable = true;
  nixpkgs.config.allowUnfree = true;

  home.stateVersion = "24.11";
}
