# Baseline for every machine (desktop or headless): nix settings, locale,
# networking, docker, and the CLI tools I expect to find everywhere.
{ pkgs, ... }:
{
  imports = [ ./docker.nix ];

  # Some general system settings
  time.timeZone = "America/Los_Angeles";
  i18n.defaultLocale = "en_US.UTF-8";
  i18n.extraLocaleSettings = {
    LC_ALL = "en_US.UTF-8";
  };
  nix.settings = {
    experimental-features = [
      "nix-command"
      "flakes"
    ];
    auto-optimise-store = true;
  };

  networking.networkmanager.enable = true;

  # Resolve <hostname>.local names (e.g. ai-box.local) via mDNS
  services.avahi = {
    enable = true;
    nssmdns4 = true;
  };
  nixpkgs.config.allowUnfree = true;

  environment.systemPackages = with pkgs; [
    # CLI tools for development
    git
    git-lfs
    just
    nixfmt # For nix code formatting

    # Languages
    python3

    # CLI Applications (general)
    tree
  ];
}
