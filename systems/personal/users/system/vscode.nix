{
  inputs,
  pkgs,
  ...
}: {
  environment.systemPackages = with pkgs; [
    just

    # add vscode with base useful extensions
    (vscode-with-extensions.override {
      vscodeExtensions = with inputs.nix-vscode-extensions.extensions.${pkgs.system}.vscode-marketplace; [
        kokakiwi.vscode-just

        # Python
        ms-python.python

        # Containerization
        ms-azuretools.vscode-docker

        # Github
        github.copilot
        github.vscode-pull-request-github
        github.vscode-github-actions

      ];
    })
  ];
}
