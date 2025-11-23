{ inputs, ... }: {
  imports = [ inputs.home-manager.nixosModules.home-manager ];

  # Initialize user
  users.users = {
    alex = {
      isNormalUser = true;
      initialPassword = "password";
      extraGroups = [ "users" "wheel" "networkmanager" "docker" ];
    };
  };

  home-manager = {

    # Sometimes when you 'nix switch' you'll get an error complaining about 
    # vs-code settings.json files already existing. This allows home manager
    # to trample over stuff, and create backups along the way. Yay!
    backupFileExtension = "backup";

    extraSpecialArgs = { inherit inputs; };
    users.alex = import ./home.nix;

  };
}
