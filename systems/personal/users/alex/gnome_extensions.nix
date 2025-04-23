{ config, pkgs, lib, ... }: {
  home.packages = with pkgs; [
    gnomeExtensions.blur-my-shell
    gnomeExtensions.paperwm
  ];

  dconf.settings = {
    ### ENABLE EXTENSIONS
    "org/gnome/shell" = {
      enabled-extensions = [
        # User installed
        pkgs.gnomeExtensions.blur-my-shell.extensionUuid
        pkgs.gnomeExtensions.paperwm.extensionUuid

        # Came with system
        pkgs.gnomeExtensions.system-monitor.extensionUuid
        pkgs.gnomeExtensions.workspace-indicator.extensionUuid
        pkgs.gnomeExtensions.auto-move-windows.extensionUuid
      ];
      disabled-extensions = [ ];
      disable-user-extensions = false;
    };

    ### EXTENSION SETTINGS

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

    # Add PaperWM specific settings here if needed, e.g.:
    "org/gnome/shell/extensions/paperwm" = {
      cycle-width-steps = [ 0.3333333333333333 0.5 0.666666666666666 ];
      default-focus-mode = 0; # "Center" is 1
    };
  };
}
