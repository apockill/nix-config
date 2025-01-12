{inputs, ...}: {
  imports = [
    inputs.home-manager.nixosModules.home-manager
  ];
    
  # Initialize user
  users.users = {
    alex = {
      isNormalUser = true;
      initialPassword = "password";
      extraGroups = ["users" "wheel" "networkmanager" "docker"];
    };
  };
  
  home-manager = {
    extraSpecialArgs = {inherit inputs;};
    users.alex = import ./home.nix;
  };
}
