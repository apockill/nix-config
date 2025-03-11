switch:
    sudo nixos-rebuild --flake .#agilite switch

update:
    sudo nix flake update
    sudo nixos-rebuild --flake .#agilite switch --upgrade

update-firmware:
    sudo fwupdmgr update

install-pipx-deps:
    pipx install tdirstat termite-ai

build-ubuntu-box:
    cd distrobox-envs && distrobox assemble  create

test-ubuntu-box:
    cd distrobox-envs/ubuntu-python/tests && \
    distrobox enter --name ubuntu -- bash -c "\
        uv sync && \
        uv run python run_tests.py"