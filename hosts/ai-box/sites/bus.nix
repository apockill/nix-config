# Locked memory for the sites bus (ai-box-apps NODE-31, DR-62). Camera frames travel in Zenoh's
# shared memory, which is mlocked: a process locks each 16 MiB pool it writes from and each pool
# it reads from, and a reader can't know how many writers it will hear. So the node library
# uses shared memory only in a process whose limit is unbounded; any other process gets the
# frames as bytes over the bus's socket, the router copying them out.
#
#   ai-box-apps-runner  every instance and the bus's router (the gateway)
#   hermes-agent        Hermes and its kanban workers: box, and the tests' runners and buses
#   agent-runner        coding jobs (agents/runner): its agents run box and the tests. It is a
#                       user unit, and a user unit can't raise a limit above its user manager's
#                       (asking anyway gets the manager's 8 MiB, silently), so the managers
#                       (user@) are unbounded too. That is every user's manager: hermes's uid
#                       isn't fixed in the config, and hermes is the only one with a manager
#                       here (lingering). user@ isn't restarted by a switch, so the limit
#                       arrives with the manager's next start (a reboot); the runner's own
#                       arrives with its next start (`agent restart`, keep-old).
#
# Sculpt's builders are agent-runner sessions too, so they get it as well. Everything else (a
# login shell, a system service of its own) keeps the default 8 MiB and gets copies.
{ config, ... }:
{
  systemd.services = {
    ai-box-apps-runner.serviceConfig.LimitMEMLOCK = "infinity";
    hermes-agent.serviceConfig.LimitMEMLOCK = "infinity";
    "user@".serviceConfig.LimitMEMLOCK = "infinity";
  };
  home-manager.users.${config.services.hermes-agent.user}.systemd.user.services.agent-runner.Service.LimitMEMLOCK =
    "infinity";
}
