{ config, pkgs, lib, ... }: {
  home.packages = with pkgs; [
    gnomeExtensions.blur-my-shell
    #    Select a window manager
    #    gnomeExtensions.pop-shell
    #    gnomeExtensions.tiling-shell
    gnomeExtensions.paperwm
  ];

  dconf.settings = {
    ### ENABLE EXTENSIONS
    "org/gnome/shell" = {
      enabled-extensions = [
        # User installed
        pkgs.gnomeExtensions.blur-my-shell.extensionUuid

        #        Select a window manager
        #        pkgs.gnomeExtensions.tiling-shell.extensionUuid
        #        pkgs.gnomeExtensions.pop-shell.extensionUuid
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
    # Configure Pop Shell
    #    "org/gnome/shell/extensions/pop-shell" = {
    #      tile-by-default = true;
    #    }; # TODO: Remove?
    #    "org/gnome/mutter" = { edge-tiling = false; };

    # Configure TilingShell
    #    "org/gnome/shell/extensions/tilingshell" = {
    #      # Window borders
    #      enable-window-border = true;
    #      window-border-width = lib.hm.gvariant.mkUint32 1;
    #      window-border-color = "rgb(26,95,180)";
    #
    #      # Key bindings
    #      tiling-system-activation-key = [ "2" ]; # Super
    #      span-multiple-tiles-activation-key = [ "1" ]; # alt
    #      tiling-system-deactivation-key = [ "-1" ]; # Disable deactivation
    #
    #      # Other
    #      enable-autotiling = true;
    #      enable-tiling-system-windows-suggestions = true;
    #      enable-screen-edges-windows-suggestions = true;
    #      restore-window-original-size =
    #        false; # When untiled, don't restore original size
    #
    #      # Map workspaces to layouts
    #      selected-layouts =
    #        [ [ "Layout 3" ] [ "Layout 4" ] [ "Layout 2" ] [ "Layout 2" ] ];
    #
    #      # JSON dump for the layouts I use
    #      layouts-json = ''
    #        [{"id":"Layout 1","tiles":[{"x":0,"y":0,"width":0.22,"height":0.5,"groups":[1,2]},{"x":0,"y":0.5,"width":0.22,"height":0.5,"groups":[1,2]},{"x":0.22,"y":0,"width":0.56,"height":1,"groups":[2,3]},{"x":0.78,"y":0,"width":0.22,"height":0.5,"groups":[3,4]},{"x":0.78,"y":0.5,"width":0.22,"height":0.5,"groups":[3,4]}]},{"id":"Layout 2","tiles":[{"x":0,"y":0,"width":0.286328125,"height":1,"groups":[1]},{"x":0.286328125,"y":0,"width":0.42734374999999997,"height":1,"groups":[2,1]},{"x":0.713671875,"y":0,"width":0.28632812500000004,"height":1,"groups":[2]}]},{"id":"Layout 3","tiles":[{"x":0,"y":0,"width":0.5,"height":1,"groups":[1]},{"x":0.5,"y":0,"width":0.49999999999999983,"height":1,"groups":[1]}]},{"id":"Layout 4","tiles":[{"x":0,"y":0,"width":0.2853515625,"height":1,"groups":[2]},{"x":0.2853515625,"y":0,"width":0.42832031249999997,"height":1,"groups":[3,2]},{"x":0.713671875,"y":0,"width":0.2863281250000001,"height":0.4928977272727273,"groups":[4,3]},{"x":0.713671875,"y":0.4928977272727273,"width":0.2863281250000001,"height":0.5071022727272725,"groups":[4,3]}]}]'';
    #    };

    # Add PaperWM specific settings here if needed, e.g.:
    "org/gnome/shell/extensions/paperwm" = {
      cycle-width-steps = [ 0.33 0.5 ];
      default-focus-mode = 0; # "Center" is 1
    };
    # PaperWM Keybindings
    "org/gnome/shell/extensions/paperwm/keybindings" = {
      # Take-window defaults to Super+T, which messes with my terminal cmd
      take-window = [ ];
    };
  };
}
