{ config, pkgs, lib, ... }: {
  imports = [
    ./dconf.nix
    ./git.nix
  ];
  
  # Enable home-manager
  programs.home-manager.enable = true;
  
  # Set home-manager state version
  home.stateVersion = "24.11";
  
}
