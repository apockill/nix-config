# Keep the GPU out of runtime suspend.
#
# Twice (2026-11-16 and 2026-11-17) the GPU got stuck in runtime_status "suspending", and the
# box then froze piece by piece. The kernel's hung-task reports on 11-17 (journalctl -b -1 -k,
# 09:58) show the chain:
# - a process reading the GPU's load waits in gk20a_busy -> __pm_runtime_resume -> rpm_resume,
#   behind the suspend that never finishes;
# - memory management stalls with it: kcompactd and khugepaged, and every process faulting in a
#   huge page, wait in drain_all_pages / lru_add_drain_all for per-CPU work that never runs;
# - llama-server, nvpmodel and the GPU tests end in uninterruptible sleep. They can't be killed,
#   so the restart hung until the box was unplugged (the watchdog fix for that is ./watchdog.nix).
#
# The GPU's runtime PM suspends it after 500 ms idle (power/control=auto). Pinning control to "on"
# means it never enters that suspend path. The cost is the GPU's idle power while nothing uses it,
# on a box that's always plugged in.
#
# The pin happens in nvpmodel's own unit. Its MAXN mode (/etc/nvpmodel.conf, POWER_MODEL ID=0)
# writes power/control "on" and then "auto" each time it runs, at boot and on every switch that
# restarts it, so a separate unit can't reliably run after it.
{
  systemd.services.nvpmodel.postStart = ''
    echo on > /sys/devices/platform/bus@0/17000000.gpu/power/control
  '';
}
