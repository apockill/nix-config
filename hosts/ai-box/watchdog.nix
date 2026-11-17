# Restarting ai-box without someone unplugging it.
#
# Twice (2026-11-16 and 2026-11-17), a restart hung during shutdown and the box stayed down until
# it was unplugged. Each time the GPU had been stuck in runtime_status "suspending" beforehand,
# with every process that touched it in uninterruptible sleep (llama-server, nvpmodel, GPU tests).
# Those processes can't be killed, so the shutdown waits on them.
#
# The hardware watchdog (Tegra186 WDT, /dev/watchdog0) is meant to reset a hung box. systemd's
# default reboot watchdog is 10 min, but this WDT's max_timeout is 255 s, so systemd can't arm it
# with that value. With no runtime watchdog, PID 1 never opens the device while the box runs.
# Both are set here within the hardware's range:
# - RuntimeWatchdogSec: PID 1 pings the watchdog all the time, so a kernel or PID 1 freeze resets the
#   box after 90 s;
# - RebootWatchdogSec: from the start of the final shutdown stage, a hang resets the box after 2 min.
#
# hermes joins systemd-journal (read-only system logs) so the agent can read where a shutdown
# hung (`journalctl -b -1`) and find the GPU's root cause. Until now it could only guess.
{
  systemd.settings.Manager = {
    RuntimeWatchdogSec = "90s";
    RebootWatchdogSec = "2min";
  };

  users.users.hermes.extraGroups = [ "systemd-journal" ];
}
