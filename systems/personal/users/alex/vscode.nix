{ inputs, pkgs, lib, ... }:
let
  marketplace =
    inputs.nix-vscode-extensions.extensions.${pkgs.system}.vscode-marketplace;

  # Pylance is unfree. The flake input evaluates it against a default (strict) nixpkgs.
  # We override the license to 'MIT' here to bypass that check locally.
  # For some reason, it's next to impossible to figure out how to get 'allowUnfree' to 
  # correctly propogate from my systems/default.nix
  pylance = marketplace.ms-python.vscode-pylance.overrideAttrs
    (old: { meta = old.meta // { license = lib.licenses.mit; }; });
in {
  programs.vscode = {
    enable = true;
    enableUpdateCheck = false;
    enableExtensionUpdateCheck = false;
    mutableExtensionsDir = true;

    extensions = with marketplace; [
      # --- JetBrains Keybindings ---
      isudox.vscode-jetbrains-keybindings

      # --- Python Suite ---
      ms-python.python
      pylance
      ms-python.debugpy

      # --- C++ Suite ---
      llvm-vs-code-extensions.vscode-clangd

      # --- Nix & DevOps ---
      jnoortheen.nix-ide
    ];

  };
}
