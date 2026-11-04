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
    nix shell --inputs-from . nixpkgs#ruff -c ruff check --select I --fix --quiet .

# Python lint: ruff, black (check only), and mypy with typed functions required.
# Tools come from this flake's nixpkgs. mypy runs once per directory, because
# several standalone scripts share a name (monitor.py).
lint:
    nix shell --inputs-from . nixpkgs#ruff nixpkgs#black nixpkgs#mypy -c sh -c '\
      ruff check . && black --check --quiet . && \
      for dir in $(git ls-files "*.py" | xargs -n1 dirname | sort -u); do \
        mypy "$dir" || exit 1; \
      done'

# Tests: each module declares its own as a Nix check under aiBox.checks
# (hosts/ai-box/checks.nix). They are built with their logs printed; a check
# that passed and hasn't changed since isn't run again.
checks := ".#checks.aarch64-linux"

# Picks the checks that don't boot a VM: all but NixOS tests needing kvm.
no_vm := 'cs: builtins.filter (n: !(cs.${n}.config.requiredFeatures.kvm or false)) (builtins.attrNames cs)'

# Every check that runs without a VM, or just the one named (`just test cc`).
test name="":
    nix build -L --no-link --keep-going {{ if name == "" { "$(just _checks " + quote(no_vm) + ")" } else { checks + "." + name } }}

# Every check, VM tests included.
test-all:
    nix build -L --no-link --keep-going $(just _checks builtins.attrNames)

# The flake attributes of the checks that `select` (a Nix function from the
# checks to a list of their names) picks.
_checks select:
    @nix eval --raw {{ checks }} --apply 'cs: toString (map (n: "{{ checks }}.${n}") (({{ select }}) cs))'

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