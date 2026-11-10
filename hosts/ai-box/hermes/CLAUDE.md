# Claude Code on ai-box

Every Claude Code session on ai-box reads this file, so it holds only what is true machine-wide. For everything else follow the instructions of the repository you work in (its `AGENTS.md`); each rule here names where to read more.

- **The machine:** an NVIDIA Jetson AGX Orin 64GB running NixOS, declared in nix-config (github.com/apockill/nix-config, host config in `hosts/ai-box/`). What survives a reboot, how it is backed up, and how to change the system: nix-config's `hosts/ai-box/hermes/AGENTS.md` (installed as `/var/lib/hermes/workspace/AGENTS.md`).
- **Installing tools:** for a one-off tool, `nix shell nixpkgs#<pkg> -c <cmd>`; never `apt`, `pip install`, `npm -g` or curl-pipe installers, which fail on NixOS or are wiped on the next switch. A project's packages go in the project's own files (that AGENTS.md, "Installing tools").
- **One hardware, one operator:** only the agent Alex has named as a device's operator (Hermes) runs code against real hardware; every other session works on simulated stand-ins and claims no device.
- **Where projects live:** web apps and their framework in `/var/lib/hermes/sites` (start from its `AGENTS.md`); long-term projects in `/var/lib/hermes/projects/<name>` (each declared in nix-config's `hosts/ai-box/projects/`); working trees for changes in `/var/lib/hermes/worktrees/`.
