# Robots on the desk. Shared access lives here; each robot gets its own file
# (its port names, quirks).
{ ... }:
{
  imports = [ ./myarm.nix ];

  # Robot arms show up as USB serial ports (/dev/ttyACM*, group dialout).
  # hermes drives them from its own sessions and from the apps under the runner.
  users.users.hermes.extraGroups = [ "dialout" ];

  # Running services only pick up a new group when they restart; listing it
  # here changes the units, so a switch restarts them with serial access.
  systemd.services.hermes-agent.serviceConfig.SupplementaryGroups = [ "dialout" ];
  systemd.services.ai-box-apps-runner.serviceConfig.SupplementaryGroups = [ "dialout" ];
}
