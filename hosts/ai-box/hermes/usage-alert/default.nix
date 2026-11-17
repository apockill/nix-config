# usage-alert: tells Alex on Discord when a disk or the memory is over 95% used (Alex, 11-14:
# "send a opus55-hermes agent to investigate if we reach over 95%"; that day the disk sat at 100%
# for six hours unnoticed). monitor.py is a cheap gate that prints OK or what is over, so no model
# runs while everything is fine. When the line changes, a Claude agent investigates read-only
# and reports what is full, the likely cause and what it recommends; it never frees anything
# itself. The job needs a terminal (Alex's explicit OK for this job), and no web; its toolsets
# are set on the job.
{
  aiBox.hermesCron.usage-alert = {
    # The gate costs a statvfs and two small reads, so ticking often is free; the model runs only
    # on a change. Every 5 minutes catches memory pressure while it builds, and a disk filling
    # as fast as the 11-14 recorder (about 6 GB an hour) would take hours to get from 95% to 100%.
    schedule = "every 5m";
    monitorScript = ./monitor.py;
    prompt = ''
      The monitor block above is usage-alert's gate for ai-box (Alex's Jetson AGX Orin home
      server). `OK` means every disk and the memory are at most 95% used. `OVER ...` names what
      is over 95%: `disk:<mount>` is a filesystem (`disk:/` is the one btrfs filesystem behind /,
      /nix, /persist, /home and /var/log), `memory` is RAM, which the Jetson's GPU shares. A
      resource stays listed until it is back at or under 93%.

      Decide from the current output and the diff:
      - OK, at the baseline or with OK before: answer exactly [SILENT].
      - OK after OVER: one short line for Alex, e.g. "Back to normal: / is at 81%." (from
        `df -h <mount>` or `free -h`).
      - Something dropped off the list and nothing new was added: one short line saying what
        is back under 93% and what is still over.
      - Something newly listed (or the baseline is OVER): investigate each new resource as
        below, then report.

      Investigate with read-only commands only, each under `timeout 600` and piped through
      `head`; commands may fail where hermes can't read (/root, /home/alex, /var/lib/docker,
      the system journal): note what you couldn't see and go on.
      Disk:
      - How full: `df -h <mount>` and `btrfs filesystem usage <mount> 2>/dev/null | head -12`
        (a small "Device unallocated" means btrfs has no room left for new chunks).
      - Biggest directories: `du -h -d 3 /persist --exclude=/persist/.snapshots 2>/dev/null |
        sort -rh | head -25`, likewise /var/log and /home; for /nix, `du -sh /nix/store` and the
        count of `/nix/var/nix/profiles/system-*-link` generations.
      - Recent growth, by directory (catches many small files like camera frames): `find /persist
        /var/log /home -path '*/.snapshots' -prune -o -type f -mtime -3 -printf '%h %s\n'
        2>/dev/null | awk '{s[$1]+=$2} END {for (d in s) printf "%.1f GB %s\n", s[d]/1e9, d}' |
        sort -rn | head -20`.
      - Snapper snapshots holding deleted data: /persist/.snapshots/<n> and /home/.snapshots/<n>
        (hourly, kept 24 hours, daily for 7 days, weekly for 4 weeks; each info.xml has the
        date). If the live directories add up to much less than the disk's used space, compare
        a suspect directory in the oldest snapshots with the live one (`du -sh
        /persist/.snapshots/<n>/snapshot/<path>`) to find data that is deleted but still held.
      - Files deleted but still open: `find /proc/[0-9]*/fd -lname '*(deleted)' -printf '%p %l\n'
        2>/dev/null | head`.
      Memory:
      - `free -h`, `grep -E 'MemAvailable|Shmem|Swap' /proc/meminfo`, `systemd-cgtop -m -b -n 1
        | head -15`, `ps -eo pid,user,rss,etime,comm --sort=-rss | head -15`. GPU memory (e.g.
        llama-cpp's loaded model) can be missing from a process's RSS but shows on its service
        in systemd-cgtop.

      Never delete, move, truncate or write files, kill or stop processes, restart services,
      run garbage collection or prune snapshots, images or caches: a scheduled job reports, and
      Alex or Hermes acts. Answer with one Discord message for Alex, under 200 words: what is
      over and how full (numbers), the likely cause with its evidence (paths, sizes, dates,
      processes), and what you recommend, as concrete commands with what each would free. Say
      plainly what you couldn't check.
    '';
  };
}
