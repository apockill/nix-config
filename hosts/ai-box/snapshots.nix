# Hourly btrfs snapshots of /persist (all state that survives a boot; the root
# itself is wiped, see state/) and /home, so a misbehaving agent's changes can
# be rolled back. Browse with `snapper -c persist list`; restore single files
# from /persist/.snapshots/<n>/snapshot/, or undo a range with
# `snapper -c persist undochange`.
{ ... }:
let
  timeline = {
    TIMELINE_CREATE = true;
    TIMELINE_CLEANUP = true;
    TIMELINE_LIMIT_HOURLY = 24;
    TIMELINE_LIMIT_DAILY = 7;
    TIMELINE_LIMIT_WEEKLY = 4;
    TIMELINE_LIMIT_MONTHLY = 0;
    TIMELINE_LIMIT_YEARLY = 0;
  };
in
{
  services.snapper.configs = {
    persist = timeline // {
      SUBVOLUME = "/persist";
    };
    home = timeline // {
      SUBVOLUME = "/home";
      ALLOW_USERS = [ "alex" ];
    };
  };
}
