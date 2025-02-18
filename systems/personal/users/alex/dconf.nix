{
  config,
  pkgs,
  lib,
  ...
}: {
  # Keybindings
  dconf.settings = {
    ### GENERAL GNOME SETTINGS
    # Set 'window focuses on hover' mode
    "org/gnome/desktop/wm/preferences" = {
      focus-mode = "sloppy";
    };

    # Enable Gnome Theming
    "org/gnome/desktop/interface" = {
      color-scheme = "prefer-dark";
      accent-color = "orange";
    };

    # Gnome Toolbar Favorite Apps
    "org/gnome/shell" = {
      favorite-apps = [
        "google-chrome.desktop"
        "dev.warp.Warp.desktop"
        "org.gnome.Nautilus.desktop"
        "org.gnome.TextEditor.desktop"
        "org.gnome.SystemMonitor.desktop"
        "spotify.desktop"
        "pycharm-professional.desktop"
        "insync.desktop"
      ];
    };

    # Wallpaper
    "org/gnome/desktop/background" = {
      picture-uri = "file:///home/alex/dotfiles/wallpapers/5120x1440-wallpaper.jpg";
      picture-uri-dark = "file:///home/alex/dotfiles/wallpapers/5120x1440-wallpaper.jpg";
      picture-options = "zoom";
    };

    # Power settings
    "org/gnome/desktop/session" = {
      # Disable screen time out because (as of 2025-01) it seems to hybernate
      idle-delay = lib.hm.gvariant.mkUint32 0;
    };
    "org/gnome/settings-daemon/plugins/power" = {
      # Disable automatic suspend when plugged in
      sleep-inactive-ac-type = "nothing";
    };
    "org/gnome/desktop/screensaver" = {
      # Disable the laptop locking when the screen turns off
      lock-enable = false;
    };

    # Turn on "Night Light"
    "org/gnome/settings-daemon/plugins/color" = {
      night-light-enabled = true;
    };

    # System Monitor Settings
    "org/gnome/gnome-system-monitor" = {
      cpu-stacked-area-chart = true;
      graph-data-points = 600;
    };

    # File explorer settings
    "org/gtk/gtk4/settings/file-chooser" = {
      # Show hidden files
      show-hidden = true;
    };
    "org/gnome/nautilus/preferences" = {
      # Show "Create symlink" in context menu
      show-create-link = true;
    };
    "org/gnome/nautilus/list-view" = {
      # Allow expanding folders when in list view
      use-tree-view = true;
    };

    # Gnome Text Editor Settings
    "org/gnome/TextEditor" = {
      indent-style = "space";
      tab-width = lib.hm.gvariant.mkUint32 4;
    };

    ### GNOME EXTENSIONS & EXTENSION SETTINGS
    # Configure Pop Shell
    "org/gnome/shell/extensions/pop-shell" = {
      tile-by-default = true;
    };
    "org/gnome/mutter" = {
      edge-tiling = false;
    };

    # Configure "Auto Move Windows" extension with specific application -> workspace pairs
    "org/gnome/shell/extensions/auto-move-windows" = {
      application-list = [
        "pycharm-professional.desktop:2"
        "spotify.desktop:4"
        "org.gnome.SystemMonitor.desktop:4"
        "insync.desktop:4"
      ];
    };

    # Enable gnome extensions
    "org/gnome/shell" = {
      enabled-extensions = [
        pkgs.gnomeExtensions.pop-shell.extensionUuid
        pkgs.gnomeExtensions.system-monitor.extensionUuid
        pkgs.gnomeExtensions.workspace-indicator.extensionUuid
        pkgs.gnomeExtensions.auto-move-windows.extensionUuid
      ];
      disabled-extensions = [];
      disable-user-extensions = false;
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

      close = ["<Super>q"];
    };
    # Disable the default "<Super>#" opening applications on the app toolbar
    "org/gnome/shell/keybindings" = {
      switch-to-application-1 = [];
      switch-to-application-2 = [];
      switch-to-application-3 = [];
      switch-to-application-4 = [];
    };

    ### APPLICATION SHORTCUTS
    # Set up per-application special keybindings
    "org/gnome/settings-daemon/plugins/media-keys" = {
      custom-keybindings = [
        "/org/gnome/settings-daemon/plugins/media-keys/custom-keybindings/screenshot-key/"
        "/org/gnome/settings-daemon/plugins/media-keys/custom-keybindings/file-explorer-key/"
        "/org/gnome/settings-daemon/plugins/media-keys/custom-keybindings/system-monitor-key/"
        "/org/gnome/settings-daemon/plugins/media-keys/custom-keybindings/terminal-key/"
        "/org/gnome/settings-daemon/plugins/media-keys/custom-keybindings/diff-key/"
        "/org/gnome/settings-daemon/plugins/media-keys/custom-keybindings/python-key/"
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

    # Pycharm Diff View
    "org/gnome/settings-daemon/plugins/media-keys/custom-keybindings/diff-key" = {
      name = "Open Diff";
      command = "pycharm-professional diff";
      binding = "<Super>D";
    };

    # Pycharm Open Empty Python File
    "org/gnome/settings-daemon/plugins/media-keys/custom-keybindings/python-key" = {
      name = "Open Python File";
      command = "pycharm-professional /tmp/scrap-python.py";
      binding = "<Super>F";
    };
  };
}
