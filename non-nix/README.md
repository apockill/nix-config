# Non Nix Systems

In the unfortunate situation I have to set up a non nix system, here's a rough workflow of my setup.


## Install Paperwm

1. Clone paperwm

```
gh repo clone paperwm/PaperWM && cd PaperWM
./install.sh
```

2. Install
3. Enable

## Install Apt Deps

1. `sudo bash install-apt-deps.sh`


## Dconf Settings

```
# Always create a backup
dconf dump / > .dconf-backup.ini

# Load
dconf load / < dconf_gnome_settings.conf
dconf load / < dconf_paperwm_settings.conf
```


