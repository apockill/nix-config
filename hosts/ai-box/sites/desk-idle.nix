# desk-idle: put the desk to sleep when nobody is using it (Alex, 2026-10-26).
#
# Hourly, desk-idle.py checks whether anything is awake (arm powered, projector
# or desk light on). If so, Gemma (local) gets the facts (desklab activities,
# minutes since the last arm command and since Claude Code last worked in
# desklab) and an overhead photo, and decides. Sleep = dock the arm on its rest
# with the motors released, projector plug off, desk light off, then a Discord
# note to Alex. No note when it decides not to (Alex's rule).
{ config, pkgs, ... }:
let
  cfg = config.services.hermes-agent;
in
{
  systemd.services.desk-idle = {
    description = "Put the desk to sleep when nobody is using it";
    serviceConfig = {
      Type = "oneshot";
      User = cfg.user;
      Group = cfg.group;
      # box, notify-alex and hermes live on the agent's own PATH.
      Environment = "PATH=/etc/profiles/per-user/${cfg.user}/bin:/run/current-system/sw/bin";
      ExecStart = "${pkgs.python3}/bin/python3 ${./desk-idle.py}";
      TimeoutStartSec = "20min";
    };
  };
  systemd.timers.desk-idle = {
    wantedBy = [ "timers.target" ];
    timerConfig = {
      # :30, clear of the hourly upgrade at ~:01 (it restarts services).
      OnCalendar = "*:30";
      RandomizedDelaySec = "5min";
    };
  };
}
