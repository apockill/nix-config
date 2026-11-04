# The root reset that makes the wipe real (the design is in ./default.nix):
#
#   root-reset         initrd service: before the root is mounted, builds a
#                      fresh @root from the declared state (./root-reset.sh,
#                      ./apply-plan.sh, following ./reset-plan.nix) and keeps
#                      the previous one as @root-old/<N>.
#   root-reset-report  once per boot: compares the old root with the new one
#                      and writes /var/lib/root-reset/report.txt
#                      (./root_reset_report.py).
{
  config,
  lib,
  pkgs,
  utils,
  ...
}:
let
  cfg = config.aiBox.state;
  # The btrfs filesystem holding @root (disko.nix).
  device = config.fileSystems."/".device;
  # Where the initrd mounts the btrfs top level while it works.
  topMount = "/run/root-reset";
  # Where the post-boot report mounts it (read-only, in its own namespace).
  reportMount = "/run/root-reset-report";
  # The initrd's log and summary, and the report; rewritten every boot.
  reportDir = "/var/lib/root-reset";
  # The kernel command-line word that skips the reset for one boot.
  keepRootParam = "ai-box.keep-root";

  plan = pkgs.writeText "root-reset-plan" (
    lib.concatMapStrings (step: "${step.action} ${step.path}\n") cfg.resetPlan
  );
  applyPlan = pkgs.writeShellApplication {
    name = "root-reset-apply-plan";
    text = builtins.readFile ./apply-plan.sh;
  };
  # Its other tools (btrfs, coreutils, mount) come from the initrd's /bin.
  rootReset = pkgs.writeShellApplication {
    name = "root-reset";
    runtimeInputs = [ applyPlan ];
    text = builtins.readFile ./root-reset.sh;
  };
  # The report imports the audit, so they sit in one directory.
  reportScripts = pkgs.runCommand "root-reset-report" { } ''
    mkdir $out
    cp ${./audit.py} $out/audit.py
    cp ${./root_reset_report.py} $out/root_reset_report.py
  '';
in
{
  options.aiBox.state.resetPlan = lib.mkOption {
    readOnly = true;
    default = import ./reset-plan.nix { inherit lib; } cfg.paths;
    defaultText = lib.literalExpression "generated from aiBox.state.paths";
    description = "The root reset's copy plan: a list of { action = \"copy\" | \"delete\"; path; }, sorted by depth.";
    type = lib.types.listOf (lib.types.attrsOf lib.types.str);
  };

  config = {
    boot.initrd.systemd = {
      # writeShellApplication's bash and coreutils are in the initrd already;
      # btrfs-progs is there for the btrfs root.
      initrdBin = [ pkgs.btrfs-progs ];
      storePaths = [
        rootReset
        applyPlan
        plan
      ];
      services.root-reset = {
        description = "Replace the root with a fresh one holding only the declared state";
        wantedBy = [ "initrd.target" ];
        requires = [ "${utils.escapeSystemdPath device}.device" ];
        after = [ "${utils.escapeSystemdPath device}.device" ];
        before = [ "sysroot.mount" ];
        unitConfig = {
          DefaultDependencies = false;
          ConditionKernelCommandLine = "!${keepRootParam}";
        };
        serviceConfig = {
          Type = "oneshot";
          ExecStart = "${rootReset}/bin/root-reset ${device} ${topMount} ${plan}";
          StandardOutput = "journal+console";
          StandardError = "journal+console";
          # A hung reset must not hang the boot. If it's stopped, the old root
          # boots unchanged (or, after the swap, the new one) and the next
          # boot keeps the leftover @root-new as an old root.
          TimeoutStartSec = "15min";
        };
      };
    };

    systemd.services.root-reset-report = {
      description = "Report what this boot's root reset deleted";
      wantedBy = [ "multi-user.target" ];
      after = [ "local-fs.target" ];
      path = [
        pkgs.btrfs-progs
        pkgs.util-linux
      ];
      # Once per boot: a switch neither reruns it nor runs it before the
      # first reset has left a summary.
      restartIfChanged = false;
      unitConfig.ConditionPathExists = "${reportDir}/info";
      serviceConfig = {
        Type = "oneshot";
        RemainAfterExit = true;
        PrivateMounts = true;
        RuntimeDirectory = "root-reset-report";
        UMask = "0022";
        Nice = 19;
        IOSchedulingClass = "idle";
        ExecStart = lib.escapeShellArgs [
          "${pkgs.python3}/bin/python3"
          "${reportScripts}/root_reset_report.py"
          cfg.declaredFile
          reportDir
          "--device"
          device
          "--mountpoint"
          reportMount
        ];
      };
    };

    aiBox.state.paths.${reportDir} = {
      backup = "ephemeral";
      why = "The root reset's log and report for this boot; rewritten on every boot (state/root-reset.nix).";
    };
  };
}
