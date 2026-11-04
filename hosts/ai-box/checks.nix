# Tests. A module's tests are a check it declares next to its code, under
# aiBox.checks; the flake exposes them all as checks.aarch64-linux, and
# `just test` builds them (see the justfile). A check is any derivation that
# fails to build when its tests fail.
#
# pytestCheck runs one directory's pytest suite in the Nix sandbox: no home
# directory, no network, nothing from the live machine. A suite gets only the
# tools it lists, taken from the packages its module ships. Its arguments:
#   dir     the suite's directory: the code and tests it runs
#   inputs  the tools the tests run (put on PATH)
{ lib, pkgs, ... }:
let
  pytest = pkgs.python3.withPackages (ps: [ ps.pytest ]);
  pytestCheck =
    name:
    {
      dir,
      inputs ? [ ],
    }:
    pkgs.runCommand "test-${name}"
      {
        nativeBuildInputs = [ pytest ] ++ inputs;
        src = dir;
      }
      ''
        cp -r --no-preserve=mode "$src" suite
        cd suite
        pytest -p no:cacheprovider -v -rs
        touch "$out"
      '';
in
{
  options.aiBox.checks = lib.mkOption {
    type = lib.types.attrsOf lib.types.package;
    default = { };
    description = "Tests, by name, as derivations that build only if they pass (flake output checks.<system>).";
  };

  config._module.args.pytestCheck = pytestCheck;
}
