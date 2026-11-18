# Antigravity (Google): everything specific to the Antigravity CLI (agy) on ai-box.
#
# Sign-in: the agent's own Google account (vault "AI Gmail Account"), on its free tier for now;
# Alex may share his plan to that account later. agy keeps the sign-in in two files (a refresh
# token in ~/.gemini, an account id in ~/.config/antigravity; no keyring on a headless user). Both
# are kept across boots, and antigravity-login restores them from the vault when the token is
# missing (a new box). Signing in as another account means a new vault item: set `loginItem`.
{
  config,
  inputs,
  lib,
  pkgs,
  ...
}:
let
  cfg = config.services.hermes-agent;
  home = cfg.stateDir;
  tokenFile = "${home}/.gemini/antigravity-cli/antigravity-oauth-token";

  # The package alex's desktop uses (users/alex/home/desktop/antigravity.nix), from the
  # antigravity-nix flake, but at 1.5.10 instead of the input's 1.5.9: over ACP, 1.5.9 drops what
  # agy says after a turn has ended (a subagent's result arriving), which 1.5.10 streams (both
  # tested on ai-box, 2026-11-17). Drop the override once the input has 1.5.10 or later.
  cli =
    inputs.antigravity-nix.packages.${pkgs.stdenv.hostPlatform.system}.google-antigravity-cli.overrideAttrs
      {
        version = "1.5.10-5253791805734912";
        src = pkgs.fetchurl {
          url = "https://storage.googleapis.com/antigravity-public/antigravity-cli/1.5.10-5253791805734912/linux-arm/cli_linux_arm64.tar.gz";
          sha512 = "f9f5c7ebc47a8b8de536acca8116b1f5a43dca614cde94008fe5a510517b23535fb281d85416930d76e76478858bf3dc66ea6d1b0c9b6eeadcfabe4d8ef2a807";
        };
      };

  # agy updates itself unless told not to: in the read-only store that only fails and logs, and
  # versions come from here anyway.
  agy = pkgs.symlinkJoin {
    name = "agy";
    paths = [ cli ];
    nativeBuildInputs = [ pkgs.makeWrapper ];
    postBuild = "wrapProgram $out/bin/agy --set AGY_CLI_DISABLE_AUTO_UPDATE 1";
  };
in
{
  options.aiBox.agents.antigravity.loginItem = lib.mkOption {
    type = lib.types.str;
    # "Antigravity CLI login (agent Google account)": a tar of the two files, relative to $HOME.
    default = "zznrrnya3h2a4j2fu5lf6j2pue";
    description = "1Password item (vault ai-assistant) holding agy's sign-in.";
  };

  config = {
    aiBox.agents.antigravity.cli = agy;
    services.hermes-agent.extraPackages = [ agy ];

    # Sessions through the runner (../runner). Over ACP agy starts in its "default" mode, whose
    # system prompt and tools differ from the TUI's; in "auto" they're the TUI's byte for byte.
    # It ignores its settings.json permission rules over ACP (accepted for now, the spike's
    # findings): don't rely on them.
    aiBox.agents.runner.agents.antigravity = {
      command = [
        "${agy}/bin/agy"
        "acp"
      ];
      mode = "auto";
      refusedEnv = [
        "GEMINI_API_KEY"
        "GOOGLE_API_KEY"
      ];
      transcript = "${home}/.gemini/antigravity-cli/brain/{session_id}/.system_generated/logs/transcript.jsonl";
    };

    # agy reads AGENTS.md in a repository and .agents/skills there natively; at user level it
    # reads ~/.gemini/AGENTS.md and ~/.gemini/config/skills.
    aiBox.agents.links = {
      "${home}/.gemini/AGENTS.md" = config.aiBox.agents.instructions;
      "${home}/.gemini/config/skills" = config.aiBox.agents.skills;
    };

    aiBox.state.paths = {
      "${home}/.gemini" = {
        backup = "cache";
        why = "Antigravity CLI state: its sign-in (refresh token; restored from the vault when missing, agents/antigravity), settings, conversations and transcripts. Not backed up: holds a token, and the history is handy, not needed.";
      };
      "${home}/.config/antigravity" = {
        backup = "cache";
        why = "The Antigravity CLI's account id that goes with its sign-in in ~/.gemini; restored from the vault with it.";
      };
    };

    systemd.services.antigravity-login = {
      description = "Restore the Antigravity CLI's sign-in from the vault when it's missing";
      wantedBy = [ "multi-user.target" ];
      requires = [ "hermes-secrets.service" ];
      after = [ "hermes-secrets.service" ];
      unitConfig = {
        ConditionPathExists = "!${tokenFile}";
        RequiresMountsFor = [
          "${home}/.gemini"
          "${home}/.config/antigravity"
        ];
      };
      path = [
        pkgs._1password-cli
        pkgs.gnugrep
        pkgs.gnutar
      ];
      environment = {
        HOME = home;
        OP_CONFIG_DIR = "/run/antigravity-login/op";
      };
      serviceConfig = {
        Type = "oneshot";
        User = cfg.user;
        Group = cfg.group;
        RuntimeDirectory = "antigravity-login";
        UMask = "0077";
      };
      # The vault token comes from the secrets file (hermes-secrets), never a command line.
      script = ''
        eval "$(grep -E '^OP_SERVICE_ACCOUNT_TOKEN=' /run/hermes-secrets/env)"
        export OP_SERVICE_ACCOUNT_TOKEN
        mkdir -p "$OP_CONFIG_DIR"
        tar=$RUNTIME_DIRECTORY/login.tar
        op document get ${config.aiBox.agents.antigravity.loginItem} --vault ai-assistant --out-file "$tar"
        tar -C "$HOME" --no-same-owner -xf "$tar"
        rm "$tar"
        test -s ${tokenFile}
        echo "restored the Antigravity CLI's sign-in from the vault"
      '';
    };
  };
}
