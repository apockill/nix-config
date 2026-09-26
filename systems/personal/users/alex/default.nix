{ inputs, ... }: {
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
    users.alex = import ./home.nix;

  };
}
