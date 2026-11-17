# notice-relay: delivers Sculpt Studio's and lab-printer's notices to people on Discord, the side
# of each app's relay that its README leaves to Hermes (ai-box-apps apps/sculpt-studio, "The
# Discord relay (Hermes)"; apps/printer, "Notices").
#
# A Hermes cron job in no-agent mode runs ./relay.py every minute: the notices are already written
# for people, so delivering them needs no model. It reads each app's notices with `box`, sends
# them with `hermes send`, and marks delivered only what was sent (details in relay.py; tests in
# ./test_relay.py, run by `just test`). Sculpt notices go to their person's Discord DM, printer
# notices (the relay's route; the studio follows its own prints) to the home channel, with photos.
# Nothing is printed while all goes well; an undelivered notice makes the run fail, which Hermes's
# cron reports on Discord.
#
# Who a Sculpt notice's `person` (the email they signed in with) is on Discord is the vault item
# "Notice relay people", read from the secrets file: this repo is public.
{
  config,
  lib,
  pkgs,
  ...
}:
let
  cfg = config.services.hermes-agent;
  hermesHome = "${cfg.stateDir}/.hermes";

  relay = pkgs.writers.writePython3Bin "notice-relay" {
    # E501 and W503 clash with black's formatting.
    flakeIgnore = [
      "E501"
      "W503"
    ];
  } (builtins.readFile ./relay.py);

  relayArgs = [
    "--sculpt"
    "lab-sculpt"
    "--printer"
    "lab-printer"
    # The home channel: Alex's DM with the bot.
    "--printer-to"
    "discord"
    # Sculpt persons that are the agent itself: its own posts (as `hermes`, or `hermes-test` in
    # its tests of the studio). Their notices have nobody to go to.
    "--agent-person"
    "hermes"
    "--agent-person"
    "hermes-test"
    # One of Hermes's media caches: `hermes send` attaches files only from those.
    "--photo-dir"
    "${hermesHome}/cache/images"
    "--log"
    "${hermesHome}/logs/notice-relay.log"
    "--box"
    "/etc/profiles/per-user/${cfg.user}/bin/box"
    "--hermes"
    "${cfg.package}/bin/hermes"
  ];
in
{
  aiBox.hermesSecrets = ''
    # Sculpt notice person -> Discord DM (hosts/ai-box/hermes/notice-relay)
    NOTICE_RELAY_PEOPLE={{ op://ai-assistant/lorndc6fyexajhtkbzumelskyq/people }}
  '';

  aiBox.hermesCron.notice-relay = {
    # The cron ticker's resolution; each run polls without waiting and takes a second or two.
    schedule = "every 1m";
    script = pkgs.writeShellScript "notice-relay.sh" "exec ${relay}/bin/notice-relay ${lib.escapeShellArgs relayArgs}";
  };
}
