# Installation
Everything in this set up is likely not "Strictly Correct (TM)", since it's my first time playing with NixOS.

## Steps

Clone the repository and symlink nix configuration
```
git clone git@github.com:apockill/dotfiles.git
cd dotfiles
sudo ln -s ~/dotfiles/configuration.nix /etc/nixos/configuration.nix
sudo ln -s ~/dotfiles/hardware-configuration.nix /etc/nixos/hardware-configuration.nix
```



