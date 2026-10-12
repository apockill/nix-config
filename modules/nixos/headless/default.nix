# Headless machine managed over the network: key-only SSH, and publishes itself
# over mDNS so it's reachable as <hostname>.local without knowing its IP.
{ pkgs, ... }:
{
  # Receiving end of `just <host>-deploy`, which rsyncs the config over
  environment.systemPackages = [ pkgs.rsync ];

  services.openssh = {
    enable = true;
    settings = {
      PasswordAuthentication = false;
      KbdInteractiveAuthentication = false;
      PermitRootLogin = "no";
    };
  };

  # Resolving .local names is set up for every host in modules/nixos/common
  services.avahi = {
    openFirewall = true;
    publish = {
      enable = true;
      addresses = true;
    };
  };
}
