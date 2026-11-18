# The agent runner: every coding agent session on ai-box, over the Agent Client Protocol (ACP).
#
# One service holds every session: it starts the agent's own ACP server for each one
# (claude-agent-acp, `agy acp`) and serves a local API on a unix socket. `agent` is its CLI and
# the service (`agent serve`): sessions, and jobs (a session named after a title, its task file the
# first message). The API is in ./README.md; the code is the typed package ./agent_runner (one
# concern per module, listed in its __init__.py), on the ACP Python SDK, pydantic, Starlette and
# uvicorn; ./tests has a test module per
# source module, the end-to-end tests against ./tests/fake_acp_agent.py, and live smoke tests that
# skip without a sign-in. The package's build runs `mypy --strict` and the tests, so a type error or
# a failing test fails the system build.
#
# It's a user service of the agent's user, not part of the Hermes gateway, so a gateway restart
# (every switch that touches it) leaves sessions running. A switch doesn't restart it either
# (keep-old); `agent restart` applies a new runner (the service exits with 75, and systemd starts
# the current version). A restart or a boot ends the agents' processes, not their sessions: the
# records stay, and the next message resumes the agent's own session (session/resume).
#
# Each vendor directory declares its agent here (aiBox.agents.runner.agents.<name>): command,
# environment, mode, transcript path. The runner itself knows only ACP.
{
  config,
  lib,
  pkgs,
  ...
}:
let
  cfg = config.services.hermes-agent;
  runnerCfg = config.aiBox.agents.runner;
  state = "${cfg.stateDir}/agent-runner";
  secretsEnv = "/run/hermes-secrets/env";

  agentsFile = pkgs.writeText "agent-runner-agents.json" (
    builtins.toJSON {
      default = runnerCfg.default;
      agents = lib.mapAttrs (_: a: {
        inherit (a)
          command
          env
          mode
          transcript
          ;
        pass_env = a.passEnv;
        claude_trust_file = a.claudeTrustFile;
        compact_window_env = a.compactWindowEnv;
      }) runnerCfg.agents;
      refused_env = lib.unique (lib.concatMap (a: a.refusedEnv) (lib.attrValues runnerCfg.agents));
      # The service runs with UMask 0077; its agents keep a user service's usual 0022, since
      # they write files in repositories others read (Caddy serves sites from them).
      agent_umask = "0022";
      parked_notify_seconds = runnerCfg.notifyUnansweredAfter * 60;
    }
  );

  py = pkgs.python3Packages;
  agentRunner = py.buildPythonApplication {
    pname = "agent-runner";
    version = "1";
    pyproject = true;
    src = lib.fileset.toSource {
      root = ./.;
      fileset = lib.fileset.unions [
        ./pyproject.toml
        (lib.fileset.fileFilter (f: f.hasExt "py") ./agent_runner)
        (lib.fileset.fileFilter (f: f.hasExt "py") ./tests)
      ];
    };
    build-system = [ py.setuptools ];
    # The ACP Python SDK (agentclientprotocol/python-sdk) and the API's web stack, from nixpkgs.
    dependencies = [
      py.agent-client-protocol
      py.pydantic
      py.starlette
      py.uvicorn
      py.httpx
    ];
    nativeCheckInputs = [
      py.pytest
      py.mypy
    ];
    # The type check and the tests are part of the build: either failing fails the toplevel. The
    # live smoke tests (tests/test_live.py) skip here: the sandbox has no sign-in.
    checkPhase = ''
      runHook preCheck
      mypy --strict agent_runner
      mypy tests
      pytest -q -p no:cacheprovider tests
      runHook postCheck
    '';
    pythonImportsCheck = [ "agent_runner" ];
    makeWrapperArgs = [
      "--set-default"
      "AGENT_RUNNER_SOCKET"
      runnerCfg.socket
      "--set-default"
      "AGENT_RUNNER_STATE"
      state
      "--set-default"
      "AGENT_RUNNER_AGENTS"
      "${agentsFile}"
      "--set-default"
      "AGENT_RUNNER_NOTIFY"
      "notify-alex"
    ];
    meta.mainProgram = "agent";
  };

  # The service gets only the secrets its agents pass through (the subscription token), read from
  # the secrets file, which may not be there yet at boot: user services can't wait for
  # hermes-secrets, a system unit.
  passEnv = lib.unique (lib.concatMap (a: a.passEnv) (lib.attrValues runnerCfg.agents));
  serve = pkgs.writeShellScript "agent-runner-serve" ''
    for _ in $(seq 60); do [ -r ${secretsEnv} ] && break; sleep 5; done
    set -a
    eval "$(${pkgs.gnugrep}/bin/grep -E '^(${lib.concatStringsSep "|" passEnv})=' ${secretsEnv})"
    set +a
    exec ${agentRunner}/bin/agent serve
  '';
in
{
  options.aiBox.agents.runner = {
    package = lib.mkOption {
      type = lib.types.package;
      internal = true;
      readOnly = true;
      default = agentRunner;
      description = "The runner's CLI and service, `agent`.";
    };
    default = lib.mkOption {
      type = lib.types.str;
      default = "claude";
      description = "The agent a session gets when `start` names none.";
    };
    socket = lib.mkOption {
      type = lib.types.str;
      readOnly = true;
      default = "${state}/sock";
      description = "The runner's API (README.md): HTTP on a unix socket (0600), the agent's user only; from inside a session only if it was started with allow_runner.";
    };
    notifyUnansweredAfter = lib.mkOption {
      type = lib.types.ints.positive;
      default = 30;
      description = "Minutes a permission or question may wait for an answer before Alex is told (once per request).";
    };
    agents = lib.mkOption {
      description = "The agents the runner can start, one per vendor directory.";
      type = lib.types.attrsOf (
        lib.types.submodule {
          options = {
            command = lib.mkOption {
              type = lib.types.listOf lib.types.str;
              description = "The agent's ACP server, speaking ACP on stdio.";
            };
            env = lib.mkOption {
              type = lib.types.attrsOf lib.types.str;
              default = { };
            };
            passEnv = lib.mkOption {
              type = lib.types.listOf lib.types.str;
              default = [ ];
              description = "Variables from the secrets file the agent gets (its sign-in); a session fails if one is missing.";
            };
            refusedEnv = lib.mkOption {
              type = lib.types.listOf lib.types.str;
              default = [ ];
              description = "Variables no session may get: they'd switch it from the subscription to metered billing.";
            };
            mode = lib.mkOption {
              type = lib.types.nullOr lib.types.str;
              default = null;
              description = "The mode every session is set to (session/set_mode); null keeps the agent's default.";
            };
            transcript = lib.mkOption {
              type = lib.types.nullOr lib.types.str;
              default = null;
              description = "Where the agent writes a session's transcript: {session_id}, {cwd}, {cwd_slug}.";
            };
            claudeTrustFile = lib.mkOption {
              type = lib.types.nullOr lib.types.str;
              default = null;
              description = "Claude Code's .claude.json, where each session's folder is marked trusted.";
            };
            compactWindowEnv = lib.mkOption {
              type = lib.types.nullOr lib.types.str;
              default = null;
              description = "The variable the agent reads its compaction window from; its value (from `env`, or a session's own) is in the session's record.";
            };
          };
        }
      );
    };
  };

  config = {
    services.hermes-agent.extraPackages = [ agentRunner ];

    aiBox.state.paths.${state} = {
      backup = "cache";
      why = "The agent runner's session records and event logs (agents/runner): the index from a session's name to the agent's own session and transcript, so a session resumes after a reboot. Transcripts themselves live with each agent (~/.claude, ~/.gemini).";
    };

    home-manager.users.${cfg.user}.systemd.user.services.agent-runner = {
      Unit = {
        Description = "The coding agents' sessions over ACP (agent serve)";
        After = [ "network-online.target" ];
        # A switch mustn't end running sessions; the new runner applies on the next start.
        X-SwitchMethod = "keep-old";
      };
      Service = {
        ExecStart = "${serve}";
        Environment = [
          "PATH=/run/wrappers/bin:/etc/profiles/per-user/${cfg.user}/bin:/run/current-system/sw/bin"
          "LANG=C.UTF-8"
          # Its cgroup is its own: a caller in it is one of its agents' processes (peers.py).
          "AGENT_RUNNER_OWN_CGROUP=1"
        ];
        # Its socket, records and event logs (tool outputs, file contents) are its user's only;
        # the user's group has other members (caddy). Agents get 0022 back (agents file).
        UMask = "0077";
        WorkingDirectory = cfg.stateDir;
        Restart = "on-failure";
        RestartSec = 5;
        # Stopping ends every agent (they run in the service's cgroup); sessions stay resumable.
        TimeoutStopSec = 30;
      };
      Install.WantedBy = [ "default.target" ];
    };
  };
}
