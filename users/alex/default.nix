# Alex's account, shared by every host. Each host layers extra home-manager
# profiles from ./home on top of ./home/common, and sets home.stateVersion.
{ inputs, ... }:
{
  imports = [ inputs.home-manager.nixosModules.home-manager ];

  # Initialize user
  users.users = {
    alex = {
      isNormalUser = true;
      initialPassword = "password";
      extraGroups = [
        "users"
        "wheel"
        "networkmanager"
        "docker"
      ];
    };
  };

  home-manager = {

    backupFileExtension = "backup";
    overwriteBackup = true;

    extraSpecialArgs = { inherit inputs; };
    users.alex.imports = [ ./home/common ];

  };
}
