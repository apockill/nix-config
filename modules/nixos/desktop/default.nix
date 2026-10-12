# GNOME workstation: display manager, sound, printing, and GUI applications.
# Only import this on machines that have a screen and a person sitting at them.
{ pkgs, ... }:
{
  imports = [
    ./1password.nix
    ./bash.nix
    ./nautilus.nix
    ./virtualbox.nix
  ];

  # Configure keymap in X11
  services.xserver.xkb = {
    layout = "us";
    variant = "";
  };

  services.printing.enable = true;

  # Firmware update manager, usable via gnome-firmware
  services.fwupd.enable = true;

  # WM Setup
  services.xserver.enable = true;
  services.displayManager.gdm.enable = true;
  services.desktopManager.gnome.enable = true;
  programs.gnome-terminal.enable = true;

  # Enable sound with pipewire.
  services.pulseaudio.enable = false;
  security.rtkit.enable = true;
  services.pipewire = {
    enable = true;
    alsa.enable = true;
    alsa.support32Bit = true;
    pulse.enable = true;
  };

  # List packages installed in system profile. To search, run:
  # $ nix search wget
  environment.systemPackages = with pkgs; [
    nautilus-open-any-terminal

    # CLI tools for development
    xhost
    distrobox
    black

    # GUI Applications
    boxbuddy # Distrobox GUI
    qdirstat
    spotify
    spotify-tray
    dconf-editor
    gnome-tweaks
    anydesk
    vlc
    gimp
    anki
    kdePackages.kdenlive

    # Screenshots
    flameshot

    # Insync
    insync
    insync-nautilus

    # Alternative package managers
    pipx

    # Firmware updates
    fwupd
    gnome-firmware
  ];
}
