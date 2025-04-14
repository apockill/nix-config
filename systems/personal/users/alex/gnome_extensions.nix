{ config, pkgs, lib, ... }: {
  home.packages = with pkgs; [
    gnomeExtensions.pop-shell
    gnomeExtensions.blur-my-shell
  ];

  dconf.settings = {
    ### ENABLE EXTENSIONS
    "org/gnome/shell" = {
      enabled-extensions = [
        # User installed
        pkgs.gnomeExtensions.pop-shell.extensionUuid
        pkgs.gnomeExtensions.blur-my-shell.extensionUuid

        # Came with system
        pkgs.gnomeExtensions.system-monitor.extensionUuid
        pkgs.gnomeExtensions.workspace-indicator.extensionUuid
        pkgs.gnomeExtensions.auto-move-windows.extensionUuid
      ];
      disabled-extensions = [ ];
      disable-user-extensions = false;
    };

    ### EXTENSION SETTINGS
    # Configure Pop Shell
    "org/gnome/shell/extensions/pop-shell" = { tile-by-default = true; };  # TODO: Remove?
    "org/gnome/mutter" = { edge-tiling = false; };

    # Configure "Auto Move Windows" extension with specific application -> workspace pairs
    "org/gnome/shell/extensions/auto-move-windows" = {
      application-list = [
        "pycharm-professional.desktop:2"
        "clion.desktop:2"
        "code.desktop:2"
        "spotify.desktop:4"
        "org.gnome.SystemMonitor.desktop:4"
        "insync.desktop:4"
      ];
    };
  };
}
