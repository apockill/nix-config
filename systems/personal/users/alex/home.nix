{ config, pkgs, lib, ... }: {
  
  dconf.settings = {
    "org/gnome/settings-daemon/plugins/media-keys" = {
      custom-keybindings = [
        "/org/gnome/settings-daemon/plugins/media-keys/custom-keybindings/screenshot-key/"
        "/org/gnome/settings-daemon/plugins/media-keys/custom-keybindings/file-explorer-key/"
        "/org/gnome/settings-daemon/plugins/media-keys/custom-keybindings/system-monitor-key/"
        "/org/gnome/settings-daemon/plugins/media-keys/custom-keybindings/terminal-key/"
      ];
    };
    
    # Screenshot
    "org/gnome/settings-daemon/plugins/media-keys/custom-keybindings/screenshot-key" = {
      name = "Take Screenshot with Flameshot";
      command = "script --command 'flameshot gui'";
      binding = "<Super>Home";
    };
    
    # File Explorer
    "org/gnome/settings-daemon/plugins/media-keys/custom-keybindings/file-explorer-key" = {
      name = "Open File Explorer";
      command = "nautilus";
      binding = "<Super>E";
    };
    
    # System Monitor
    "org/gnome/settings-daemon/plugins/media-keys/custom-keybindings/system-monitor-key" = {
      name = "Open System Monitor";
      command = "gnome-system-monitor";
      binding = "<Primary><Shift>Escape";
    };
    
    # Terminal
    "org/gnome/settings-daemon/plugins/media-keys/custom-keybindings/terminal-key" = {
      name = "Open Terminal";
      command = "warp-terminal";
      binding = "<Super>T";
    };
  };
  
  # Enable home-manager
  programs.home-manager.enable = true;
  
  home.stateVersion = "24.11";
}
