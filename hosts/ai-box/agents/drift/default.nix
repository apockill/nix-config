# Drift guards (SKEPTIC.md, "Drift"): what the agent runner assumes about its vendors, checked
# where it can move. The pins are local, so nothing moves at run time; what moves is the vendors'
# service side and whatever a lock update brings.
#   ../claude/skew.nix  claude-agent-acp's bundled SDK and the CLI are one release (fails the build)
#   canary.py           agents-canary (with evidence.py, what it reads, and private_runner.py, its
#                       own `agent serve`): a private runner, one short Claude Haiku session (and an
#                       Antigravity Flash turn once it's signed in), one stable line per assumption;
#                       daily in monitor mode, and by hand for a PR that moves flake.lock,
#                       agents/claude/acp.nix or agents/antigravity (hermes/AGENTS.md)
#   digest.py           agents-usage-digest: the last day's Claude usage as alert states (cache
#                       hits, big contexts, usage-limit errors, idle sessions, failed notices to
#                       Alex); daily in monitor mode
# Both crons are a script first: the model runs only when a line changes. The scripts' tests and
# mypy --strict are part of the system build.
{
  config,
  lib,
  pkgs,
  ...
}:
let
  cfg = config.services.hermes-agent;
  home = cfg.stateDir;
  runner = config.aiBox.agents.runner;
  agent = "${runner.package}/bin/agent";
  python = pkgs.python3;
  passEnv = lib.unique (lib.concatMap (a: a.passEnv) (lib.attrValues runner.agents));

  src = lib.fileset.toSource {
    root = ./.;
    fileset = lib.fileset.fileFilter (f: f.hasExt "py") ./.;
  };

  canary = pkgs.writeShellScriptBin "agents-canary" ''
    exec ${python}/bin/python3 ${src}/canary.py \
      --agent ${agent} \
      --instructions ${config.aiBox.agents.instructions} \
      --secrets /run/hermes-secrets/env \
      ${lib.concatMapStringsSep " " (n: "--pass-env ${n}") passEnv} \
      --home ${home} \
      --agy-token ${home}/.gemini/antigravity-cli/antigravity-oauth-token \
      "$@"
  '';
  digest = pkgs.writeShellScriptBin "agents-usage-digest" ''
    exec ${python}/bin/python3 ${src}/digest.py \
      --projects ${home}/.claude/projects --agent ${agent} "$@"
  '';

  # Hermes runs a monitor script with its own Python, by extension (.py): this one only runs the
  # package's command, whose output is the monitor's. It always exits 0: Hermes takes a failing
  # script as an error, not a change, so "FAIL canary: couldn't run" must be output to wake anyone.
  monitor =
    pkg: name:
    pkgs.writeText "${name}-monitor.py" ''
      import subprocess

      subprocess.run(["${pkg}/bin/${name}"])
    '';

  tests =
    pkgs.runCommand "agents-drift-tests"
      {
        nativeBuildInputs = [
          (python.withPackages (ps: [
            ps.pytest
            ps.mypy
          ]))
        ];
      }
      ''
        cp ${src}/*.py . && chmod u+w *.py
        mypy --strict --cache-dir=/dev/null canary.py evidence.py private_runner.py digest.py
        mypy --cache-dir=/dev/null test_canary.py test_evidence.py test_digest.py
        pytest -q -p no:cacheprovider test_canary.py test_evidence.py test_digest.py
        touch $out
      '';
in
{
  options.aiBox.agents.drift = {
    canary = lib.mkOption {
      type = lib.types.package;
      readOnly = true;
      default = canary;
      description = "agents-canary, for this configuration's runner and agents (build it from a branch to check that branch).";
    };
    digest = lib.mkOption {
      type = lib.types.package;
      readOnly = true;
      default = digest;
      description = "agents-usage-digest.";
    };
  };

  config = {
    services.hermes-agent.extraPackages = [
      canary
      digest
    ];
    system.checks = [ tests ];

    # About 20 s and a Haiku session of ~20k cached tokens a day.
    aiBox.hermesCron.agents-canary = {
      schedule = "15 6 * * *";
      monitorScript = monitor canary "agents-canary";
      prompt = ''
        The monitor block above is agents-canary's report for ai-box's agent runner
        (nix-config hosts/ai-box/agents/drift/canary.py): one line per assumption the runner makes
        about Claude Code, claude-agent-acp and the Antigravity CLI, `ok`, `FAIL` or `skip`.
        - Only `ok` and `skip` lines, unchanged from before: answer exactly [SILENT].
        - A version changed (`claude-versions`, `agy-versions`) and nothing failed: one short line
          for Alex naming the new versions.
        - A line turned `FAIL` (or `FAIL canary: couldn't run`): tell Alex in under 120 words which
          assumption broke and what the canary saw (the line says both), and that Hermes can rerun
          it with `agents-canary` and read canary.py's docstring for what each check guards. Don't
          change anything yourself.
        - A `FAIL` line went back to `ok`: one line saying it recovered.
      '';
    };

    aiBox.hermesCron.agents-usage-digest = {
      schedule = "0 7 * * *";
      monitorScript = monitor digest "agents-usage-digest";
      prompt = ''
        The monitor block above is agents-usage-digest's alert states for the last day of Claude
        usage on ai-box (nix-config hosts/ai-box/agents/drift/digest.py, whose docstring explains
        each alert).
        - Every line `ok`, as before: answer exactly [SILENT].
        - An alert started: tell Alex in under 120 words which alert started and what crossed which
          line (the line says), and that `agents-usage-digest --details` gives the numbers. For
          notify, notify-alex itself is failing, so say so plainly.
        - Never suggest a smaller compaction window or anything else that trades agent quality
          for quota: those changes need Alex's own review.
        - An alert ended: one line saying so.
        Don't stop or message any session yourself.
      '';
    };
  };
}
