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

    # "Cloudflare Tunnel"
    CLOUDFLARE_TUNNEL_TOKEN={{ op://ai-assistant/pb7y4zmd5omz4jq5crf7h3fqsa/token }}

    # "Cloudflare Access" (Service Token)
    CF_ACCESS_CLIENT_ID={{ op://ai-assistant/mikp2glua2oqvkkvqbmwvntmje/client_id }}
    CF_ACCESS_CLIENT_SECRET={{ op://ai-assistant/mikp2glua2oqvkkvqbmwvntmje/client_secret }}
  '';

  # The only privileged commands the agent may run:
  # 1. Switch ai-box to whatever is merged on master.
  # Executes via systemd-run so it escapes hermes-agent's private mount namespace
  # (where /nix is read-only) and runs in the host root namespace.
  # Attempts a clean live switch first. If pre-switch checks inhibit a live switch
  # (e.g. kernel/firmware/driver updates), falls back to `boot` to stage into the
  # bootloader without breaking running services, prompting for a reboot.
  switchToMasterWorker = pkgs.writeShellScript "ai-box-switch-worker" ''
    export HOME=/root
    echo "Attempting live switch to master..."
    if ${config.system.build.nixos-rebuild}/bin/nixos-rebuild switch \
        --refresh --flake github:apockill/nix-config#ai-box; then
      echo "Live switch to master succeeded."
    else
      echo "Live switch inhibited or failed. Staging to bootloader instead..."
      if ${config.system.build.nixos-rebuild}/bin/nixos-rebuild boot \
          --refresh --flake github:apockill/nix-config#ai-box; then
        echo ">>> STAGED_REBOOT_REQUIRED: System staged to bootloader. Ask user before rebooting. <<<"
      else
        echo "Build failed for both switch and boot."
        exit 1
      fi
    fi
  '';

  switchToMaster = pkgs.writeShellScriptBin "ai-box-switch-to-master" ''
    exec ${pkgs.systemd}/bin/systemd-run \
      --unit=ai-box-switch-run \
      --wait \
      --collect \
      --property=Environment="HOME=/root" \
      --property=WorkingDirectory=/root \
      ${switchToMasterWorker}
  '';
  switchToMasterPath = "/run/current-system/sw/bin/ai-box-switch-to-master";
  ai-box-switch = pkgs.writeShellScriptBin "ai-box-switch" ''
    exec sudo ${switchToMasterPath}
  '';

  # 2. Test a local branch live without changing the bootloader.
  # Ephemeral: hourly autoUpgrade (or reboot) automatically reverts to master.
  testLocalConfigWorker = pkgs.writeShellScript "ai-box-test-worker" ''
    export HOME=/root
    exec ${config.system.build.nixos-rebuild}/bin/nixos-rebuild test \
      --flake ${workspace}/nix-config#ai-box
  '';

  testLocalConfig = pkgs.writeShellScriptBin "ai-box-test-local" ''
    exec ${pkgs.systemd}/bin/systemd-run \
      --unit=ai-box-test-run \
      --wait \
      --collect \
      --property=Environment="HOME=/root" \
      --property=WorkingDirectory=/root \
      ${testLocalConfigWorker}
  '';
  testLocalConfigPath = "/run/current-system/sw/bin/ai-box-test-local";
  ai-box-test = pkgs.writeShellScriptBin "ai-box-test" ''
    exec sudo ${testLocalConfigPath}
  '';

  # 3. Reboot the machine when staged updates require it (ask Alex first!).
  rebootCmd = pkgs.writeShellScriptBin "ai-box-reboot-cmd" ''
    exec ${pkgs.systemd}/bin/systemctl reboot
  '';
  rebootCmdPath = "/run/current-system/sw/bin/ai-box-reboot-cmd";
  ai-box-reboot = pkgs.writeShellScriptBin "ai-box-reboot" ''
    exec sudo ${rebootCmdPath}
  '';

  # Upstream Hermes bug (NousResearch/hermes-agent issue #108335 / PR #129628):
  # When using 1Password Service Accounts (OP_SERVICE_ACCOUNT_TOKEN), `op item get`
  # requires an explicit `--vault` flag. Upstream Hermes omits `--vault` in
  # agent/vault_backends/onepassword.py, causing `browser_vault_fill` to fail.
  # This wrapper injects `--vault ai-assistant` on `item get` calls when omitted.
  # Remove this wrapper once upstream hermes-agent merges support for service accounts.
  opVaultWrapper = pkgs.writeShellScriptBin "op" ''
    if [[ "$*" == *"item get"* && "$*" != *"--vault"* ]]; then
      exec ${pkgs._1password-cli}/bin/op "$@" --vault ai-assistant
    else
      exec ${pkgs._1password-cli}/bin/op "$@"
    fi
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
      cron = {
        allow_agent_scheduling = false;
        model = "gemma-4-26b-a4b";
        model_provider = "local";
      };

      providers.local = {
        name = "local";
        base_url = "http://127.0.0.1:8080/v1";
      };

      # Persistent Chromium on virtual display with remote debugging (CDP)
      browser = {
        cdp_url = "http://127.0.0.1:9222";
      };

      # Website logins come from 1Password and are filled straight into the
      # browser; the model never sees them.
      vault.onepassword = {
        enabled = true;
        service_account_token_env = "OP_SERVICE_ACCOUNT_TOKEN";
        binary_path = "${opVaultWrapper}/bin/op";
      };
      # Lets `op` and `gh` in the agent's terminal reach the vault and GitHub,
      # and gives curl access to the Cloudflare Access service token.
      # Cron has no terminal, so it never gets these.
      terminal.env_passthrough = [
        "OP_SERVICE_ACCOUNT_TOKEN"
        "GH_TOKEN"
        "CF_ACCESS_CLIENT_ID"
        "CF_ACCESS_CLIENT_SECRET"
      ];
    };

    # SOUL.md and AGENTS.md are installed by hermes-instructions below, not
    # with hermesHomeFiles/documents (those overwrite on every activation).
    workingDirectory = workspace;

    extraPackages = with pkgs; [
      opVaultWrapper
      ai-box-switch
      ai-box-test
      ai-box-reboot
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
    # op needs a writable config dir and a system service has no $HOME
    environment.OP_CONFIG_DIR = "${secretsDir}/op";
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
      mkdir -p -m 0700 "$OP_CONFIG_DIR"
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
    wants = [ "hermes-secrets.service" ];
    after = [ "hermes-secrets.service" ];
    serviceConfig = {
      EnvironmentFile = [ "${secretsDir}/env" ];
      NoNewPrivileges = lib.mkForce false;
      ProtectSystem = lib.mkForce false;
    };
  };

  environment.systemPackages = [
    switchToMaster
    testLocalConfig
    rebootCmd
  ];
  users.users.${cfg.user}.extraGroups = [ "video" ];
  security.sudo.extraRules = [
    {
      users = [ cfg.user ];
      commands = [
        {
          command = "${switchToMasterPath}";
          options = [ "NOPASSWD" ];
        }
        {
          command = "${testLocalConfigPath}";
          options = [ "NOPASSWD" ];
        }
        {
          command = "${rebootCmdPath}";
          options = [ "NOPASSWD" ];
        }
      ];
    }
  ];
}
