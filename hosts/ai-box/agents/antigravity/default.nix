# Antigravity (Google): everything specific to the Antigravity CLI (agy) on ai-box.
#
# Sign-in: Alex's personal Google account by default (loginItem, vault ai-assistant; the agent's
# own free-tier account is kept as a separate vault item). agy keeps the sign-in in two files (a
# refresh token in ~/.gemini, an account id in ~/.config/antigravity; no keyring on a headless
# user). Both are kept across boots, and antigravity-login restores them from the vault when the
# token is missing (a new box). Signing in as another account means a new vault item: set `loginItem`.
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
  # antigravity-nix flake. Keep it at 1.5.10 or later: over ACP, 1.5.9 drops what agy says after
  # a turn has ended (a subagent's result arriving), which 1.5.10 streams (tested on ai-box,
  # 2026-11-17).
  cli = inputs.antigravity-nix.packages.${pkgs.stdenv.hostPlatform.system}.google-antigravity-cli;

  # agy updates itself unless told not to: in the read-only store that only fails and logs, and
  # versions come from here anyway.
  agy = pkgs.symlinkJoin {
    name = "agy";
    paths = [ cli ];
    nativeBuildInputs = [ pkgs.makeWrapper ];
    postBuild = "wrapProgram $out/bin/agy --set AGY_CLI_DISABLE_AUTO_UPDATE 1";
  };

  # Hermes model-provider plugin (Nous official plugin-catalog, pure stdlib) that runs Hermes
  # main chat and cron jobs on the Antigravity subscription through the official `agy` binary
  # rather than metered Google AI Studio API keys.
  hermesPlugin = pkgs.fetchFromGitHub {
    owner = "soyelmismo";
    repo = "hermes-antigravity-subscription";
    rev = "f1c1a8ccc5a560b8d5926e2b7e4b544d272d2dd2"; # v1.0.29
    hash = "sha256-0ECTK7SNo2z2wOCAvGJbf0KI2ctexue8k7/JcfqX+Iw=";
  };
in
{
  options.aiBox.agents.antigravity.loginItem = lib.mkOption {
    type = lib.types.str;
    # "Antigravity CLI login (Alex personal account)": a tar of the two files, relative to $HOME.
    # Agent Google account (free tier) item: "zznrrnya3h2a4j2fu5lf6j2pue".
    default = "jp5f2bnoimkmx66cnw67qfjgmm";
    description = "1Password item (vault ai-assistant) holding agy's sign-in.";
  };

  config = {
    aiBox.agents.antigravity.cli = agy;
    services.hermes-agent.extraPackages = [ agy ];

    # Sessions through the runner (../runner). Over ACP agy starts in its "default" mode, whose
    # system prompt and tools differ from the TUI's; in "auto" they're the TUI's byte for byte.
    # Even in "auto", agy ignores settings.json permission rules over ACP and asks before
    # outside-workspace access or some commands; `--dangerously-skip-permissions` disables tool
    # permission prompts for headless runner sessions (kept off the wrapped `agy` binary itself,
    # since hermes-antigravity-subscription relies on omitting it to deny agy tools during Hermes
    # inference turns).
    aiBox.agents.runner.agents.antigravity = {
      command = [
        "${agy}/bin/agy"
        "acp"
        "--dangerously-skip-permissions"
      ];
      mode = "auto";
      refusedEnv = [
        "GEMINI_API_KEY"
        "GOOGLE_API_KEY"
      ];
      transcript = "${home}/.gemini/antigravity-cli/brain/{session_id}/.system_generated/logs/transcript.jsonl";
    };

    # agy reads AGENTS.md in a repository and .agents/skills there natively; at user level it
    # reads ~/.gemini/AGENTS.md and ~/.gemini/config/skills. Hermes discovers user model-provider
    # plugins under ~/.hermes/plugins/model-providers/<name>/.
    aiBox.agents.links = {
      "${home}/.gemini/AGENTS.md" = config.aiBox.agents.instructions;
      "${home}/.gemini/config/skills" = config.aiBox.agents.skills;
      "${home}/.hermes/plugins/model-providers/antigravity-subscription-directsdk" = "${hermesPlugin}";
    };

    # Ensure Hermes sees the restored Antigravity sign-in, the symlinked plugin, and the wrapped
    # `agy` binary on a fresh box or after a plugin update.
    systemd.services.hermes-agent = {
      wants = [
        "antigravity-login.service"
        "home-manager-${cfg.user}.service"
      ];
      after = [
        "antigravity-login.service"
        "home-manager-${cfg.user}.service"
      ];
      restartTriggers = [ hermesPlugin ];
      environment.ANTIGRAVITY_COMMAND = "${agy}/bin/agy";
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
