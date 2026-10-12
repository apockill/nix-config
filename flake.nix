{
  inputs = {
    home-manager = {
      url = "github:nix-community/home-manager/release-26.05";
      inputs.nixpkgs.follows = "nixpkgs";
    };

    nixpkgs.url = "github:nixos/nixpkgs/nixos-26.05";
    nix-vscode-extensions.url = "github:jcszymansk/nix-vscode-extensions";

    antigravity-nix = {
      url = "github:jacopone/antigravity-nix";
      inputs.nixpkgs.follows = "nixpkgs";
    };

    claude-code-nix = {
      url = "github:sadjow/claude-code-nix";
    };

    # Jetson (ai-box) support. jetpack-nixos tracks the same NixOS release.
    jetpack-nixos = {
      url = "github:anduril/jetpack-nixos";
      inputs.nixpkgs.follows = "nixpkgs";
    };

    # Declarative disk partitioning, used to install ai-box onto its NVMe
    disko = {
      url = "github:nix-community/disko";
      inputs.nixpkgs.follows = "nixpkgs";
    };
  };

  outputs =
    { self, nixpkgs, ... }@inputs:
    let
      mkHost =
        hostDir:
        nixpkgs.lib.nixosSystem {
          specialArgs = { inherit inputs; };
          modules = [ hostDir ];
        };
    in
    {
      nixosConfigurations = {
        agilite = mkHost ./hosts/agilite;
        ai-box = mkHost ./hosts/ai-box;
      };

      # Firmware flash script for ai-box, run from an x86_64 machine (NVIDIA's
      # flashing tools are x86_64-only). The firmware and kernel it flashes still
      # run on the Jetson, so this variant of ai-box is cross-compiled from
      # x86_64 to aarch64. CUDA is turned off because nixpkgs can't cross-compile
      # it, and flashing doesn't need it. See hosts/ai-box/README.md.
      packages.x86_64-linux.ai-box-flash-script =
        (self.nixosConfigurations.ai-box.extendModules {
          modules = [
            {
              nixpkgs.buildPlatform = "x86_64-linux";
              hardware.nvidia-jetpack.configureCuda = false;
            }
          ];
        }).config.system.build.flashScript;
    };
}
