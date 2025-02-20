switch:
    sudo nixos-rebuild --flake .#agilite switch

update:
    sudo nix flake update

update-firmware:
    sudo fwupdmgr update

install-pipx-deps:
    pipx install tdirstat termite-ai

build-ubuntu-box:
    cd distrobox-envs && distrobox assemble  create
