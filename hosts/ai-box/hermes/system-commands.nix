# The only privileged commands the agent may run. Each has two halves:
#
#   <name>       agent-facing wrapper, on the agent's PATH (extraPackages)
#   <name>-root  runs as root via a NOPASSWD sudo rule for exactly that path
#
# Removing a command = deleting its entry below; nothing else references them.
{
  config,
  pkgs,
  ...
}:
let
  cfg = config.services.hermes-agent;
  workspace = "${cfg.stateDir}/workspace";
  logDir = "${cfg.stateDir}/.hermes/logs";
  nixos-rebuild = "${config.system.build.nixos-rebuild}/bin/nixos-rebuild";
  rootBin = name: "/run/current-system/sw/bin/${name}-root";

  # Root half: run `worker` as its own transient systemd unit. That escapes
  # hermes-agent's sandbox (its mount namespace has /nix read-only) and keeps
  # the work alive if hermes-agent is restarted while it runs.
  rootUnit =
    name: worker:
    pkgs.writeShellScriptBin "${name}-root" ''
      exec ${pkgs.systemd}/bin/systemd-run \
        --pipe \
        --unit=${name}-run \
        --wait \
        --collect \
        --property=Environment="HOME=/root" \
        --property=Environment="PATH=/run/current-system/sw/bin" \
        --property=WorkingDirectory=/root \
        ${worker}
    '';

  # Agent half for anything that may restart the agent mid-run (switch/test).
  # `--pipe` hands the unit the caller's stdout. If that were the agent's
  # pipe, the agent dying would kill the rebuild on its next write, leaving
  # services stopped until the hourly upgrade (two ~30 min outages). So
  # stdout goes to a log file that we follow; if the agent dies, the rebuild
  # keeps writing to the file and finishes. Cost: one short gateway restart.
  survivableWrapper =
    name:
    pkgs.writeShellScriptBin name ''
      log=${logDir}/${name}.log
      echo "=== ${name} started $(date -Is) ===" >"$log"
      sudo ${rootBin name} </dev/null >>"$log" 2>&1 &
      pid=$!
      ${pkgs.coreutils}/bin/tail -n +1 -f --pid="$pid" "$log"
      wait "$pid"
      rc=$?
      echo "=== ${name} finished $(date -Is): exit $rc ===" | ${pkgs.coreutils}/bin/tee -a "$log"
      exit "$rc"
    '';

  # ai-box-switch: apply whatever is merged on master. Tries a live switch;
  # if pre-switch checks inhibit it (kernel/firmware/driver updates), stages
  # to the bootloader instead and asks for a reboot.
  switchWorker = pkgs.writeShellScript "ai-box-switch-worker" ''
    echo "Attempting live switch to master..."
    if ${nixos-rebuild} switch --refresh --flake github:apockill/nix-config#ai-box; then
      echo "Live switch to master succeeded."
    else
      echo "Live switch inhibited or failed. Staging to bootloader instead..."
      if ${nixos-rebuild} boot --refresh --flake github:apockill/nix-config#ai-box; then
        echo ">>> STAGED_REBOOT_REQUIRED: System staged to bootloader. Ask user before rebooting. <<<"
      else
        echo "Build failed for both switch and boot."
        exit 1
      fi
    fi
  '';

  # ai-box-test: activate the local checkout without touching the bootloader.
  # Ephemeral: the hourly autoUpgrade (or a reboot) reverts to master.
  testWorker = pkgs.writeShellScript "ai-box-test-worker" ''
    export NIXOS_NO_CHECK=1
    ${nixos-rebuild} test --flake path:${workspace}/nix-config#ai-box
    rc=$?
    echo ">>> ai-box-test worker exit $rc <<<"
    exit $rc
  '';

  # ai-box-reboot: for staged updates. The agent asks Alex first. Refuses while
  # undeclared state exists (see hosts/ai-box/state), unless given --force.
  rebootRoot = pkgs.writeShellScriptBin "ai-box-reboot-root" ''
    if [ "''${1:-}" != "--force" ]; then
      if ! out=$(${config.aiBox.state.checkCommand}); then
        echo "Refusing to reboot: the root filesystem is wiped on boot, and these"
        echo "paths aren't declared, so rebooting would delete them:"
        echo "$out"
        echo "Declare it in hosts/ai-box/state/paths.nix, or rerun with --force (ask Alex)."
        exit 1
      fi
    fi
    exec ${pkgs.systemd}/bin/systemctl reboot
  '';
  rebootWrapper = pkgs.writeShellScriptBin "ai-box-reboot" ''
    exec sudo ${rootBin "ai-box-reboot"} "$@"
  '';

  rootCommands = [
    (rootUnit "ai-box-switch" switchWorker)
    (rootUnit "ai-box-test" testWorker)
    rebootRoot
  ];
in
{
  services.hermes-agent.extraPackages = [
    (survivableWrapper "ai-box-switch")
    (survivableWrapper "ai-box-test")
    rebootWrapper
  ];

  environment.systemPackages = rootCommands;

  security.sudo.extraRules = [
    {
      users = [ cfg.user ];
      commands = map (pkg: {
        command = "/run/current-system/sw/bin/${pkg.name}";
        options = [ "NOPASSWD" ];
      }) rootCommands;
    }
  ];
}
