{ config, ... }: {


  programs.dconf.enable = true;
  
  programs.dconf.settings = {
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

}
