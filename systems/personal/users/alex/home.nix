{ config, pkgs, lib, ... }: {
  
  dconf.settings = {
    "org/gnome/settings-daemon/plugins/media-keys" = {
      custom-keybindings = [
        "/org/gnome/settings-daemon/plugins/media-keys/custom-keybindings/screenshot-key/"
      ];
    };
  
    "org/gnome/settings-daemon/plugins/media-keys/custom-keybindings/screenshot-key" = {
      name = "Take Screenshot with satty";
      command = "satty";
      binding = "<Primary>Home";  # Ctrl + Home
    };
  };
  
  # Enable home-manager
  programs.home-manager.enable = true;
  
  home.stateVersion = "24.11";
}
