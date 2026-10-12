# Hermes Agent (github.com/NousResearch/hermes-agent): Alex's always-on agent.
#
# Secrets never live in this repo or the Nix store. The only secret on disk is
# the 1Password service-account token in /etc/hermes/op-service-account.env
# (root-only, scoped to the `ai-assistant` vault). At boot, hermes-secrets
# fetches everything else from that vault into a RAM-only env file.
{
  config,
  inputs,
  lib,
  pkgs,
  ...
}:
let
  cfg = config.services.hermes-agent;
  hermesHome = "${cfg.stateDir}/.hermes";
  workspace = "${cfg.stateDir}/workspace";

  # The agent may edit its instructions on disk (and keeps a PR in sync), so
  # these are installed only when the repo's version changes, not on every
  # activation. Stamps are root-owned so the agent can't suppress an update.
  instructions = {
    "${hermesHome}/SOUL.md" = ./SOUL.md;
    "${workspace}/AGENTS.md" = ./AGENTS.md;
    "${workspace}/TODO.md" = ./TODO.md;
  };
  stampDir = "/var/lib/hermes-instructions";

  serviceAccountEnv = "/etc/hermes/op-service-account.env";
  secretsDir = "/run/hermes-secrets";

  # `op inject` template: only references, no secrets. Items live in the
  # ai-assistant vault; IDs instead of titles so renames don't break boot.
  secretsTemplate = pkgs.writeText "hermes-secrets.tpl" ''
    # Gemini API key
    GOOGLE_API_KEY={{ op://ai-assistant/szznxwsb7suugqxkj5gwo5v6iq/credential }}

    # "Discord bot": token, Alex's user ID (the only allowed user), and the
    # channel for messages Hermes starts on its own
    DISCORD_BOT_TOKEN={{ op://ai-assistant/4mwy5sy5dcie5fnlf5jwzxemuy/credential }}
    DISCORD_ALLOWED_USERS={{ op://ai-assistant/4mwy5sy5dcie5fnlf5jwzxemuy/user_id }}
    DISCORD_HOME_CHANNEL={{ op://ai-assistant/4mwy5sy5dcie5fnlf5jwzxemuy/channel_id }}

    # "GitHub": the ailex-agent account's token, used by gh and git
    GH_TOKEN={{ op://ai-assistant/kb6xnh67wvh2hu7gtl3cgzxu4u/token }}
  '';

  # The only privileged command the agent may run: switch ai-box to whatever is
  # merged on master. It takes no arguments, so unmerged changes can't be
  # deployed this way. (A wrapper because sudoers can't hold the flake ref's
  # `:` and `#` unescaped.)
  switchToMaster = pkgs.writeShellScriptBin "ai-box-switch-to-master" ''
    exec ${config.system.build.nixos-rebuild}/bin/nixos-rebuild switch \
      --refresh --flake github:apockill/nix-config#ai-box
  '';
  switchToMasterPath = "/run/current-system/sw/bin/ai-box-switch-to-master";
  ai-box-switch = pkgs.writeShellScriptBin "ai-box-switch" ''
    exec sudo ${switchToMasterPath}
  '';
in
{
  imports = [ inputs.hermes-agent.nixosModules.default ];

  services.hermes-agent = {
    enable = true;

    settings = {
      # Main model for conversations Alex starts. The -latest alias tracks
      # Google's newest Flash model.
      model = {
        default = "gemini-flash-latest";
        provider = "gemini";
        base_url = "https://generativelanguage.googleapis.com/v1beta";
      };

      # Scheduled jobs only read, check, summarize, and report back: no
      # terminal, files, browser (which carries the vault), or delegation.
      platform_toolsets.cron = [
        "web"
        "vision"
        "session_search"
      ];
      cron.allow_agent_scheduling = false;

      # Website logins come from 1Password and are filled straight into the
      # browser; the model never sees them.
      vault.onepassword = {
        enabled = true;
        service_account_token_env = "OP_SERVICE_ACCOUNT_TOKEN";
      };
      # Lets `op` and `gh` in the agent's terminal reach the vault and GitHub.
      # Cron has no terminal, so it never gets these.
      terminal.env_passthrough = [
        "OP_SERVICE_ACCOUNT_TOKEN"
        "GH_TOKEN"
      ];
    };

    # SOUL.md and AGENTS.md are installed by hermes-instructions below, not
    # with hermesHomeFiles/documents (those overwrite on every activation).
    workingDirectory = workspace;

    extraPackages = with pkgs; [
      _1password-cli
      ai-box-switch
      gh
      git
      jq
      just
      nix
      ripgrep
    ];
  };

  # Pull secrets from 1Password into RAM before the agent starts. Rotating a
  # secret = change it in 1Password, then `systemctl restart hermes-secrets
  # hermes-agent`.
  systemd.services.hermes-secrets = {
    description = "Fetch Hermes secrets from 1Password";
    wants = [ "network-online.target" ];
    after = [ "network-online.target" ];
    before = [ "hermes-agent.service" ];
    requiredBy = [ "hermes-agent.service" ];
    unitConfig.ConditionPathExists = serviceAccountEnv;
    path = [ pkgs._1password-cli ];
    serviceConfig = {
      Type = "oneshot";
      RemainAfterExit = true;
      EnvironmentFile = serviceAccountEnv;
      RuntimeDirectory = "hermes-secrets";
      RuntimeDirectoryMode = "0750";
      UMask = "0077";
    };
    script = ''
      out=${secretsDir}/env
      # The network can be up before DNS/TLS to 1Password works; retry briefly.
      for attempt in 1 2 3 4 5 6; do
        if op inject --force --in-file ${secretsTemplate} --out-file "$out.tmp"; then
          break
        fi
        [ "$attempt" = 6 ] && exit 1
        sleep 10
      done
      echo "OP_SERVICE_ACCOUNT_TOKEN=$OP_SERVICE_ACCOUNT_TOKEN" >> "$out.tmp"
      chgrp ${cfg.group} "$out.tmp" ${secretsDir}
      chmod 0640 "$out.tmp"
      mv "$out.tmp" "$out"
    '';
  };

  system.activationScripts.hermes-instructions = lib.stringAfter [ "hermes-agent-setup" ] ''
    mkdir -p ${stampDir}
    chmod 0700 ${stampDir}
    ${lib.concatStrings (
      lib.mapAttrsToList (dst: src: ''
        stamp=${stampDir}/$(echo ${dst} | tr / _).sha256
        if [ ! -e ${dst} ] || [ "$(cat "$stamp" 2>/dev/null)" != "${builtins.hashFile "sha256" src}" ]; then
          install -o ${cfg.user} -g ${cfg.group} -m 0660 -D ${src} ${dst}
          echo ${builtins.hashFile "sha256" src} > "$stamp"
        fi
      '') instructions
    )}
  '';

  systemd.services.hermes-agent = {
    requires = [ "hermes-secrets.service" ];
    after = [ "hermes-secrets.service" ];
    serviceConfig.EnvironmentFile = [ "${secretsDir}/env" ];
  };

  environment.systemPackages = [ switchToMaster ];
  security.sudo.extraRules = [
    {
      users = [ cfg.user ];
      commands = [
        {
          # `""` = no arguments allowed
          command = ''${switchToMasterPath} ""'';
          options = [ "NOPASSWD" ];
        }
      ];
    }
  ];
}
