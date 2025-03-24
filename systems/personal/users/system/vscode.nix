{
  inputs,
  pkgs,
  ...
}: {

  nixpkgs.overlays = [ inputs.nix-vscode-extensions.overlays.default ];

  environment.systemPackages = with pkgs; [

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
