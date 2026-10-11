{ ... }:
{
  # 1Password is configured at the NixOS level (not home-manager) so that the
  # setuid/setgid wrappers and polkit policy needed for CLI <-> GUI integration,
  # system authentication unlock, and browser extension integration get installed.
  programs._1password.enable = true;
  programs._1password-gui = {
    enable = true;
    # Users allowed to unlock 1Password via polkit (system auth / fingerprint)
    polkitPolicyOwners = [ "alex" ];
  };
}
