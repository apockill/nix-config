# Headless machine managed over the network: key-only SSH and mDNS so it's
# reachable as <hostname>.local without knowing its IP.
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

  services.avahi = {
    enable = true;
    nssmdns4 = true;
    openFirewall = true;
    publish = {
      enable = true;
      addresses = true;
    };
  };
}
