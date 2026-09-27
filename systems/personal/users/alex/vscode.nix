{
  inputs,
  pkgs,
  lib,
  config,
  ...
}:
let
  marketplace =
    inputs.nix-vscode-extensions.extensions.${pkgs.stdenv.hostPlatform.system}.vscode-marketplace;

  # Some packages are unfree. The flake input evaluates it against a default (strict) nixpkgs.
  # We override the license to 'MIT' here to bypass that check locally.
  # For some reason, it's next to impossible to figure out how to get 'allowUnfree' to
  # correctly propogate from my systems/default.nix
  pylance = marketplace.ms-python.vscode-pylance.overrideAttrs (old: {
    meta = old.meta // {
      license = lib.licenses.mit;
    };
  });
  cpptools = marketplace.ms-vscode.cpptools.overrideAttrs (old: {
    meta = old.meta // {
      license = lib.licenses.mit;
    };
  });
  claudeCode = pkgs.vscode-utils.extensionFromVscodeMarketplace {
    name = "claude-code";
    publisher = "Anthropic";
    version = "2.1.283";
    sha256 = "sha256-zhIrfEE7gL11xw83Hc/wbfpq5Ss0Awgi5OF+vDTzdHI=";
  };
in
{
  programs.vscode = {
    enable = true;
    mutableExtensionsDir = true;

    profiles.default = {
      enableUpdateCheck = false;
      enableExtensionUpdateCheck = false;

      userSettings = {
        # --- C / C++ & Clangd Settings ---
        # Delegate code intelligence to clangd while keeping cpptools for debugging
        "C_Cpp.intelliSenseEngine" = "disabled";
      };

      keybindings = [
        # Keybindings for toggling between diff editor
        {
          key = "ctrl+shift+d";
          command = "git.openFile";
          when = "isInDiffEditor";
        }
        {
          key = "ctrl+shift+d";
          command = "git.openChange";
          when = "editorFocus && !isInDiffEditor";
        }
        {
          key = "ctrl+shift+d";
          command = "git.openFile";
          when = "focusedView == 'workbench.scm'";
        }
      ];

      extensions = with marketplace; [
        # --- JetBrains Keybindings ---
        isudox.vscode-jetbrains-keybindings

        # --- Python Suite ---
        ms-python.python
        pylance
        ms-python.debugpy

        # --- C++ Suite ---
        cpptools
        llvm-vs-code-extensions.vscode-clangd

        # --- Nix & DevOps ---
        jnoortheen.nix-ide
        mkhl.direnv

        # --- AI Assistants ---
        claudeCode
      ];
    };
  };

  # Solution adapted from bemyak in https://github.com/nix-community/home-manager/issues/1800#issuecomment-2262881846
  # This replaces the read-only symlink with a writable copy using 'install'
  home.activation.makeVSCodeConfigWritable = {
    after = [ "writeBoundary" ];
    before = [ ];
    data = ''
      for file in settings.json keybindings.json; do
        configPath="${config.home.homeDirectory}/.config/Code/User/$file"

        # If the file is a symlink (which Home Manager generates), 
        # overwrite it with a writable copy of its target.
        if [ -L "$configPath" ]; then
          install -m 0640 "$(readlink "$configPath")" "$configPath"
        fi
      done
    '';
  };
}
