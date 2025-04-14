{ inputs, pkgs, ... }: {

  # If I don't do this, I'll get errors about asking for non-free packages from vscode
  # By doing this, somehow my allow_nonfree setting from nixpkgs gets passed in
  nixpkgs.overlays = [ inputs.nix-vscode-extensions.overlays.default ];

  environment.systemPackages = with pkgs; [
    # Add cursor (ai IDE) here too, since it's vscode adjacent
    code-cursor

    # add vscode with base useful extensions
    (vscode-with-extensions.override {
      vscodeExtensions = with pkgs.vscode-marketplace; [
        kokakiwi.vscode-just

        # Python
        ms-python.python

        # Containerization
        ms-azuretools.vscode-docker
        ms-vscode-remote.remote-containers
        ms-vscode-remote.remote-ssh
        ms-vscode.remote-server

        # Github
        github.copilot
        github.vscode-pull-request-github
        github.vscode-github-actions

      ];
    })
  ];
}
