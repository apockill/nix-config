# Installation
Everything in this set up is likely not "Strictly Correct (TM)", since it's my first time playing with NixOS.

## Steps

Clone the repository and symlink nix configuration
```shell
git clone git@github.com:apockill/dotfiles.git
cd dotfiles
sudo nixos-rebuild --flake . switch
```

To update packages, use
```shell
sudo nix flake update
```


If you run into an error about "blah blah does not provide attribute..." it's possible you're changing the hostname from what existed prior. If so, you may need to run the following once (assumes agilite is your hostname):

```shell
sudo nixos-rebuild --flake .#agilite switch
```

Next, it's probably a good idea to make sure your firmware is up to date. You can do
this via `gnome-firmware`, or CLI:
```shell
sudo fwupdmgr update
```

Finally, it's time to handle "Non-Nix State". There's not really a good way to manage 
python executables that aren't on the nixpkgs, so just run this once:

```bash
pipx install tdirstat termite-ai
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
docker compose -f distrobox-envs/docker-compose.yml build && \
distrobox create \
  --name ubuntu \
  --image alex-ubuntu-python-box \
  --additional-flags "--runtime=nvidia" \
  --init-hooks 'echo "export PATH=\"/usr/bin:/bin:/usr/local/bin:\$PATH\"" > /etc/profile.d/clean_path.sh && chmod +x /etc/profile.d/clean_path.sh'
```

### Troubleshooting Distrobox display passthrough:

`Failed to initialize GLEW`: Workaround by setting `export XDG_SESSION_TYPE=x11`
