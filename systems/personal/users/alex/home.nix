{ config, pkgs, lib, ... }: {
  # Enable home-manager
  programs.home-manager.enable = true;
  
  # Set home-manager state version
  home.stateVersion = "24.11";
  
  # Keybindings
  dconf.settings = {
    # Enable gnome extensions
    "org/gnome/shell" = {
      enabled-extensions = [pkgs.gnomeExtensions.pop-shell.extensionUuid];
      disabled-extensions = [];
      disable-user-extensions = false;
    };
    
    # Set 'window focuses on hover' mode
    "org/gnome/desktop/wm/preferences" = {
      focus-mode = "sloppy";
    };
    
    # Gnome Theming
    "org/gnome/desktop/interface" = {
      color-scheme = "prefer-dark";
      accent-color = "orange";
    };
    
    # Set up window moving / workspace moving key bindings
    "org/gnome/desktop/wm/keybindings" = {     
      
      move-to-workspace-1 = ["<Alt><Super>1"];
      move-to-workspace-2 = ["<Alt><Super>2"];
      move-to-workspace-3 = ["<Alt><Super>3"];
      move-to-workspace-4 = ["<Alt><Super>4"];
      
      switch-to-workspace-1 = ["<Super>1"];
      switch-to-workspace-2 = ["<Super>2"];
      switch-to-workspace-3 = ["<Super>3"];
      switch-to-workspace-4 = ["<Super>4"];
    };
    
    # Set up per-application special keybindings
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
}
