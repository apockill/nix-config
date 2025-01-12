# Installation
Everything in this set up is likely not "Strictly Correct (TM)", since it's my first time playing with NixOS.

## Steps

Clone the repository and symlink nix configuration
```
git clone git@github.com:apockill/dotfiles.git
cd dotfiles
sudo nixos-rebuild --flake . switch
```


If you run into an error about "blah blah does not provide attribute..." it's possible you're chaning the hostname from what existed prior. If so, you may need to run the following once (assumes agilite is your hostname):

```
sudo nixos-rebuild --flake .#agilite switch
```
