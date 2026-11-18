# Locked memory for the sites bus (ai-box-apps NODE-31, DR-62). Camera frames travel in Zenoh's
# shared memory, which is mlocked: a process locks each 16 MiB pool it writes from and each pool
# it reads from, and a reader can't know how many writers it will hear. So the node library
# uses shared memory only in a process whose limit is unbounded; any other process gets the
# frames as bytes over the bus's socket, the router copying them out.
#
#   ai-box-apps-runner  every instance and the bus's router (the gateway)
#   hermes-agent        Hermes and its kanban workers: box, and the tests' runners and buses
#   cc-tmux             Claude Code jobs: box and the tests; restartIfChanged is false there,
#                       so its jobs get the limit from the unit's next start
#
# Everything else (a login shell, Sculpt's builder sessions, which only run box) keeps the
# default 8 MiB and gets copies.
{
  systemd.services = {
    ai-box-apps-runner.serviceConfig.LimitMEMLOCK = "infinity";
    hermes-agent.serviceConfig.LimitMEMLOCK = "infinity";
    cc-tmux.serviceConfig.LimitMEMLOCK = "infinity";
  };
}
