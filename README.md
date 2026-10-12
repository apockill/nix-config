# Installation
Everything in this set up is likely not "Strictly Correct (TM)", since it's my first time playing with NixOS.

## Layout

| Path | What lives there |
|---|---|
| `hosts/<name>/` | One directory per machine. Picks hardware, roles, users, and which home profiles apply. |
| `hardware/<model>/` | Hardware-specific config (`dell-xps-15`, `jetson-agx-orin`). |
| `modules/nixos/common/` | Baseline for every machine: nix settings, locale, docker, CLI tools. |
| `modules/nixos/desktop/` | GNOME workstation role (GUI apps, sound, printing). |
| `modules/nixos/headless/` | Network-managed machine role (key-only SSH, mDNS). |
| `users/alex/` | Alex's account, shared by every host. |
| `users/alex/home/common/` | Home profile used everywhere (git, direnv, CLI tooling). |
| `users/alex/home/desktop/` | Home profile for GNOME machines (dconf, VS Code, browsers). |

Hosts:
- `agilite`: personal Dell XPS 15 workstation (`just switch`).
- `ai-box`: Jetson AGX Orin running AI services and agents (`just ai-box-deploy`).
  See [hosts/ai-box/README.md](hosts/ai-box/README.md) for installing it from scratch.

## Steps

Clone the repository and symlink nix configuration
```shell
git clone git@github.com:apockill/dotfiles.git
cd dotfiles
```

To switch:
```shell
just switch
```

To update packages, use
```shell
just update
```

Next, it's probably a good idea to make sure your firmware is up to date. You can do
this via `gnome-firmware`, or:
```shell
just update-firmware
```

Finally, it's time to handle "Non-Nix State". This includes a few pipx packages, and a 
local set of python tooling I use, stored under `./tools/. 
There's not really a good way to manage python executables that aren't on the nixpkgs, 
so just run this command once:

```bash
just install-pipx-deps
```

## GPU Profiles

If your hardware/*/ configuration configures `system76-power`, 
you can switch graphics profiles via:

- GPU Disabled: `system76-power graphics integrated`
- Everything on integrated, GPU On: `system76-power graphics compute`
  
  **WARNING**: For whatever reason, this can cause docker containers running CUDA to not 
               find libcuda.so. Don't ask me why.
- Everything on GPU: `system76-power graphics nvidia`

You may see `org.freedesktop.DBus.Error.Failed` errors, but it seems that profile 
switching still works regardless of the error.

# Development Tips

I typically use Nix for my personal system, and distrobox+(poetry/other language specific
package managers) to containerize all of my projects.

Upon creating a system, I run the following to create all of my usual distroboxes:
```shell
just build-ubuntu-box
```

Then I validate the distrobox tests work, hardware passthrough works, and X passthrough
works by running:
```shell
just test-ubuntu-box
```

## Troubleshooting
If you change vscode settings, and get an error from vscode:
```
Nov 23 14:05:19 agilite systemd[1]: home-manager-alex.service: Main process exited, code=exited, status=1/FAILURE
Nov 23 14:05:19 agilite systemd[1]: home-manager-alex.service: Failed with result 'exit-code'.
Nov 23 14:05:19 agilite systemd[1]: Failed to start Home Manager environment for alex.
```

What's happening is nix is trying to clobber an existing `settings.json.backup` file. You can fix this by:
```
rm /home/$USER/.config/Code/User/settings.json.backup
just switch
```
