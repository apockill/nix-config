# Home profile for GNOME workstations: desktop settings and GUI apps.
{ ... }:
{
  imports = [
    ./dconf.nix
    ./gnome_extensions.nix
    ./chrome.nix
    ./vscode.nix
    ./antigravity.nix
  ];
}
