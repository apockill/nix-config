# Recover a lost NVMe completion interrupt after 2 s instead of 30 s.
#
# Every few hours the kernel logs `nvme nvme0: I/O <n> QID <q> timeout, completion polled`
# (109 times from 2026-11-04 to 11-25, every boot, same 5.15 kernel throughout). "Completion
# polled" means the drive had finished the command, but its MSI never reached the driver; the
# block layer's timeout handler then polls the queue, finds the completion and carries on, with
# no abort or reset. Until then every process waiting on that I/O stalls, for the whole timeout
# (default 30 s): the 11-25 09:38 stall cost a calibration run its 2 s control lease.
#
# The interrupts are lost on Orin's PCIe side: with JetPack 6's PCIe driver, every MSI goes
# through the DesignWare controller's MSI demux on CPU0 (all nvme0q* counts in /proc/interrupts
# are on CPU0). NVIDIA's forum reports the same message on AGX Orin with WD, Kingston, SK Hynix
# and Crucial drives; turning APST or ASPM off didn't help there (ASPM L1 is already off here),
# and the community GICv2m kernel + device-tree patch is what stopped it.
#
# This only shortens each stall: the queue's io_timeout (ms) is how long the block layer waits
# before polling. A command that is really still running at 2 s gets an NVMe Abort and is
# retried, and a second timeout resets the controller; `journalctl -k | grep -E 'nvme.*(abort|reset)'`
# shows if that ever happens. Writing sysfs applies at once, at boot and on a live switch,
# with no reboot.
{
  systemd.services.nvme-io-timeout = {
    description = "NVMe I/O timeout 2 s (Orin loses some NVMe MSIs)";
    wantedBy = [ "multi-user.target" ];
    serviceConfig = {
      Type = "oneshot";
      RemainAfterExit = true;
    };
    script = ''
      for timeout in /sys/block/nvme*n*/queue/io_timeout; do
        echo 2000 > "$timeout" # 2 s
      done
    '';
  };
}
