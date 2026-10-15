# Users are fully declared: NixOS regenerates /etc/passwd, /etc/shadow and
# friends from this config on every boot, so they aren't state. The only user
# state is alex's password hash, kept in ${passwordDir}/alex.
#
# Change alex's password:
#   mkpasswd -m yescrypt | sudo tee /var/lib/user-passwords/alex >/dev/null
#   then ai-box-switch (or reboot).
{
  config,
  lib,
  pkgs,
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

  # One-time migration: seed the hash file from the password alex set with
  # `passwd` while users were mutable. Runs before NixOS rewrites /etc/shadow
  # from the config, and never overwrites an existing hash file. Activation
  # runs with a minimal PATH, so tools are referenced by store path.
  system.activationScripts.seedUserPasswords.text = ''
    ${pkgs.coreutils}/bin/install -d -m 0700 ${passwordDir}
    if [ ! -s ${passwordDir}/alex ]; then
      hash=$(${pkgs.gawk}/bin/awk -F: '$1 == "alex" { print $2 }' /etc/shadow)
      case "$hash" in
        '$'*)
          (umask 077; printf '%s\n' "$hash" > ${passwordDir}/alex)
          echo "seeded ${passwordDir}/alex from /etc/shadow"
          ;;
        *) echo "warning: no password hash for alex in /etc/shadow; not seeding" >&2 ;;
      esac
    fi
  '';
  system.activationScripts.users.deps = [ "seedUserPasswords" ];

  assertions = [
    {
      assertion = lib.all (u: u.initialPassword == null && u.password == null) (
        lib.attrValues config.users.users
      );
      message = "With users.mutableUsers = false, initialPassword/password set the real password on every boot. Use hashedPasswordFile (see hosts/ai-box/state/users.nix).";
    }
  ];
}
