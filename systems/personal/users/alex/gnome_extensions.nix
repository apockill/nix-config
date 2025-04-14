{ config, pkgs, lib, ... }: {
  home.packages = with pkgs; [
    gnomeExtensions.pop-shell
    gnomeExtensions.blur-my-shell
    gnomeExtensions.another-window-session-manager
  ];

  dconf.settings = {
    # Enable gnome extensions
    "org/gnome/shell" = {
      enabled-extensions = [
        # User installed
        pkgs.gnomeExtensions.pop-shell.extensionUuid
        pkgs.gnomeExtensions.another-window-session-manager.extensionUuid
        pkgs.gnomeExtensions.blur-my-shell.extensionUuid

        # Came with system
        pkgs.gnomeExtensions.system-monitor.extensionUuid
        pkgs.gnomeExtensions.workspace-indicator.extensionUuid
        pkgs.gnomeExtensions.auto-move-windows.extensionUuid
      ];
      disabled-extensions = [ ];
      disable-user-extensions = false;
    };
  };
}
