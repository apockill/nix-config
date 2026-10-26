# The agent's Gmail (ailex.agent.bot@gmail.com): everything email in one place.
#
# - Hermes' built-in email gateway: mail from the allowlist is a message to
#   Hermes, like Discord, answered by email in the same thread. The allowlist
#   is the vault item "Email allowlist" (owned by Alex; Alex and Bethany), so no
#   personal address lands in this public repo. The gateway also drops
#   unauthenticated From: and automated senders (no-reply, bulk) even when
#   allowlisted, and ignores everyone else.
# - notify-alex: lets a session that didn't start on Discord (an email) post to
#   Alex's DM. AGENTS.md: every allowlisted email gets a short Discord note.
# - himalaya: the agent's own inbox from the terminal (skill agent-mail).
#
# Vault items: "AI Gmail App Password (IMAP)", "Email allowlist". 2FA backup
# codes for the account: "AI Gmail 2FA backup codes".
{ config, pkgs, ... }:
let
  cfg = config.services.hermes-agent;
  address = "ailex.agent.bot@gmail.com";
  appPassword = "op://ai-assistant/2rc2yvkz6qo4xvcftyyenvvpk4/password";
  secretsEnv = "/run/hermes-secrets/env";

  # `hermes send` needs the Discord bot token, which only the gateway's
  # environment has ("Platform 'discord' is not configured" from an email
  # session). Read it and the home channel from the secrets file for the one
  # call, like ghWrapper does for GH_TOKEN.
  notifyAlex = pkgs.writeShellScriptBin "notify-alex" ''
    set -a
    eval "$(${pkgs.gnugrep}/bin/grep -E '^DISCORD_(BOT_TOKEN|HOME_CHANNEL)=' ${secretsEnv})"
    set +a
    exec hermes send --quiet --to discord "$@"
  '';
in
{
  aiBox.hermesSecrets = ''
    # Email gateway (./email.nix)
    EMAIL_ADDRESS=${address}
    EMAIL_PASSWORD={{ ${appPassword} }}
    EMAIL_IMAP_HOST=imap.gmail.com
    EMAIL_SMTP_HOST=smtp.gmail.com
    # Sender authentication trusts only Gmail's own Authentication-Results;
    # without this pin the gateway rejects every sender (fail-closed).
    EMAIL_AUTHSERV_ID=mx.google.com
    EMAIL_ALLOWED_USERS={{ op://ai-assistant/ej3omo5n7ljkuttiav3xfvj6lq/password }}
  '';

  services.hermes-agent.extraPackages = [ notifyAlex ];

  # The password comes from the vault at use, never stored on disk.
  home-manager.users.${cfg.user} = {
    programs.himalaya.enable = true;
    accounts.email.accounts.agent = {
      primary = true;
      inherit address;
      userName = address;
      realName = "Ailex (Alex's assistant)";
      flavor = "gmail.com";
      passwordCommand = "op read ${appPassword}";
      himalaya.enable = true;
    };
  };
}
