# Users are fully declared: NixOS regenerates /etc/passwd, /etc/shadow and
# friends from this config on every boot, so they aren't state. The only user
# state is alex's password hash, kept in ${passwordDir}/alex.
#
# Change alex's password:
#   mkpasswd -m yescrypt | sudo tee /var/lib/user-passwords/alex >/dev/null
#   then apply it: sudo nixos-rebuild switch --flake github:apockill/nix-config#ai-box
#   (or ask the agent to run ai-box-switch, or reboot). `passwd` has no lasting
#   effect: /etc/shadow is rebuilt from this config.
# On a new box, write the file the same way (as root, e.g. from nixos-enter)
# before the first boot; without it alex has no password.
{
  config,
  lib,
  ...
}:
let
  passwordDir = "/var/lib/user-passwords";
in
{
  users.mutableUsers = false;

  users.users.alex = {
    # users/alex sets initialPassword for other hosts; here it would become
    # the real password on every boot if the hash file were missing.
    initialPassword = lib.mkForce null;
    hashedPasswordFile = "${passwordDir}/alex";
  };

  assertions = [
    {
      assertion = lib.all (u: u.initialPassword == null && u.password == null) (
        lib.attrValues config.users.users
      );
      message = "With users.mutableUsers = false, initialPassword/password set the real password on every boot. Use hashedPasswordFile (see hosts/ai-box/state/users.nix).";
    }
  ];
}
