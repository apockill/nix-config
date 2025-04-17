switch:
    sudo nixos-rebuild --flake .#agilite switch

update:
    sudo nix flake update
    sudo nixos-rebuild --flake .#agilite switch --upgrade

update-firmware:
    sudo fwupdmgr update

format:
    nixfmt .
    black .

install-pipx-deps:
    pipx install tdirstat termite-ai
    pipx install ./tools --force


build-ubuntu-box:
    cd distrobox-envs && \
    docker compose build && \
    distrobox assemble  create

test-ubuntu-box:
    cd distrobox-envs/ubuntu-python/tests && \
    distrobox enter --name ubuntu -- bash -c "\
        uv sync && \
        uv run python run_tests.py"