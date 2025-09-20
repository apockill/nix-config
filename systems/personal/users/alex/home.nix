{ config, pkgs, lib, ... }: {
  imports =
    [ ./dconf.nix ./git.nix ./gnome_extensions.nix ./chrome.nix ];

  # Enable home-manager
  programs.home-manager.enable = true;
  nixpkgs.config.allowUnfree = true;

  # Set home-manager state version
  home.stateVersion = "24.11";
}
