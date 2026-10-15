switch:
    sudo nixos-rebuild --flake .#agilite switch

update:
    nix flake update
    sudo nixos-rebuild --flake .#agilite switch

update-firmware:
    sudo fwupdmgr update

# Copy this checkout to ai-box and switch there (it's aarch64, so it builds on
# the box). Prompts for alex's sudo password on ai-box.
ai-box-deploy:
    rsync -a --delete --exclude .git --exclude result ./ alex@ai-box.local:nix-config/
    ssh -t alex@ai-box.local sudo nixos-rebuild switch --flake path:/home/alex/nix-config#ai-box

# Flash ai-box's firmware over USB; the Jetson must be in recovery mode.
# See hosts/ai-box/README.md
ai-box-flash:
    nix build .#ai-box-flash-script
    sudo ./result/bin/initrd-flash-orin-agx-devkit

format:
    nixfmt .
    black .

# Python unit tests, with pytest from this flake's nixpkgs (nothing to install).
test:
    nix shell --inputs-from . nixpkgs#python3Packages.pytest -c pytest hosts

install-pipx-deps:
    pipx install tdirstat termite-ai
    pipx install --editable ./tools --force


build-ubuntu-box:
    cd distrobox-envs && \
    docker compose build && \
    distrobox assemble  create

test-ubuntu-box:
    cd distrobox-envs/ubuntu-python/tests && \
    distrobox enter --name ubuntu -- bash -c "uv sync && uv run python run_tests.py"