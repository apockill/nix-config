# Edit this configuration file to define what should be installed on
# your system.  Help is available in the configuration.nix(5) man page
# and in the NixOS manual (accessible by running ‘nixos-help’).

{ config, pkgs, ... }:

{
  imports =
    [ 
      ./users
    ];

  # Bootloader.
  boot.loader.systemd-boot.enable = true;
  boot.loader.efi.canTouchEfiVariables = true;

  # networking.wireless.enable = true;  # Enables wireless support via wpa_supplicant.

  # Some general system settings
  networking.hostName = "agilite"; # Define your hostname.
  time.timeZone = "America/Los_Angeles";
  i18n.defaultLocale = "en_US.UTF-8";
  i18n.extraLocaleSettings = {
    LC_ALL = "en_US.UTF-8";
  };
  nix.settings = {
    experimental-features = ["nix-command" "flakes"];
    auto-optimise-store = true;
  };

  # Configure keymap in X11
  services.xserver.xkb = {
    layout = "us";
    variant = "";
  };

  # System setup
  networking.networkmanager.enable = true;
  services.printing.enable = true;
  nixpkgs.config.allowUnfree = true;

  # Firmware update manager, usable via gnome-firmware
  services.fwupd.enable = true;

  # WM Setup
  services.xserver.enable = true;
  services.xserver.displayManager.gdm.enable = true;
  services.xserver.desktopManager.gnome.enable = true;

  # Enable sound with pipewire.
  hardware.pulseaudio.enable = false;
  security.rtkit.enable = true;
  services.pipewire = {
    enable = true;
    alsa.enable = true;
    alsa.support32Bit = true;
    pulse.enable = true;
  };

  # Enable touchpad support (enabled default in most desktopManager).
  # services.xserver.libinput.enable = true;


  # List packages installed in system profile. To search, run:
  # $ nix search wget
  environment.systemPackages = with pkgs; [
    # Extensions (gnome or otherwise)
    gnomeExtensions.pop-shell
    nautilus-open-any-terminal
  
    # CLI tools for development
    git
    git-lfs
    xorg.xhost
    
    # GUI Applications
    jetbrains.pycharm-professional
    warp-terminal
    qdirstat
    spotify
    spotify-tray
    google-chrome
    dconf-editor
    gnome-tweaks
    anydesk
    vlc
    gimp
    kdenlive

    # CLI Applications
    tree
    
    # Screenshots
    flameshot
    
    # Insync
    insync
    insync-emblem-icons  # Untested if needed
    insync-nautilus

    # Developer tooling (non GUI)
    uv
    poetry

    # Alternative package managers
    pipx

    # Firmware updates
    pkgs.fwupd
    gnome-firmware
  ];

  # Some programs need SUID wrappers, can be configured further or are
  # started in user sessions.
  # programs.mtr.enable = true;
  # programs.gnupg.agent = {
  #   enable = true;
  #   enableSSHSupport = true;
  # };

  # List services that you want to enable:

  # Enable the OpenSSH daemon.
  # services.openssh.enable = true;

  # Open ports in the firewall.
  # networking.firewall.allowedTCPPorts = [ ... ];
  # networking.firewall.allowedUDPPorts = [ ... ];
  # I disabled the firewall in a moment of frustration when network_mode: host was
  # acting oddly in docker (with regards to ROS). I may come to regret this.
  networking.firewall.enable = false;

  # This value determines the NixOS release from which the default
  # settings for stateful data, like file locations and database versions
  # on your system were taken. It‘s perfectly fine and recommended to leave
  # this value at the release version of the first install of this system.
  # Before changing this value read the documentation for this option
  # (e.g. man configuration.nix or on https://nixos.org/nixos/options.html).
  system.stateVersion = "24.11"; # Did you read the comment?

}
