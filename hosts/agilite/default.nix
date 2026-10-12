# agilite: Alex's personal Dell XPS 15 workstation.
{ ... }:
{
  imports = [
    ../../hardware/dell-xps-15
    ../../modules/nixos/common
    ../../modules/nixos/desktop
    ../../users/alex
  ];

  # Layer the GNOME/GUI home profile on top of alex's common one
  home-manager.users.alex = {
    imports = [ ../../users/alex/home/desktop ];
    home.stateVersion = "24.11";
  };

  # Bootloader.
  boot.loader.systemd-boot.enable = true;
  # Prevent old generations from filling up the 512MB EFI /boot partition
  boot.loader.systemd-boot.configurationLimit = 10;
  # Prevents 'bootctl update' from failing when it detects the older bootloader
  # on the secondary 1TB SSD (nvme1n1) while /boot is already up to date
  boot.loader.systemd-boot.graceful = true;
  boot.loader.efi.canTouchEfiVariables = true;

  networking.hostName = "agilite"; # Define your hostname.

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
