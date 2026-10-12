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
      # Public keys allowed to SSH in as alex. Only matters on hosts that run an
      # SSH server (e.g. ai-box); agilite doesn't.
      openssh.authorizedKeys.keys = [
        # agilite (Dell XPS 15), ~/.ssh/id_ed25519: alex's day-to-day machine
        "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIFPKb5yMfTuTbBHmkNRyDZDl83VyobpHIBcuwIdbvYYJ alex@agilite"
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
