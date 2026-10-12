switch:
    sudo nixos-rebuild --flake .#agilite switch

update:
    nix flake update
    sudo nixos-rebuild --flake .#agilite switch

update-firmware:
    sudo fwupdmgr update

# ai-box is aarch64, so build on the box itself and activate it over SSH
ai-box-deploy:
    nixos-rebuild --flake .#ai-box --target-host alex@ai-box.local --build-host alex@ai-box.local --sudo switch

# Flash ai-box's firmware over USB; the Jetson must be in recovery mode.
# See hosts/ai-box/README.md
ai-box-flash:
    nix build .#ai-box-flash-script
    sudo ./result/bin/initrd-flash-orin-agx-devkit

format:
    nixfmt .
    black .

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