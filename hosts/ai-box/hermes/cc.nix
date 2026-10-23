# `cc`: the agent's Claude Code jobs as Remote Control sessions, so Alex can
# watch and steer them from claude.ai/code or the Claude app while they run.
#
# Each job is an interactive `claude --remote-control` in its own tmux session.
# Remote Control needs the full `claude auth login` (stored in
# ~/.claude/.credentials.json); the long-lived CLAUDE_CODE_OAUTH_TOKEN can't
# open Remote Control sessions and takes precedence, so jobs run without it.
# Plain `claude -p` keeps using the token, as the fallback when the login lapses.
#
# The tmux server runs as its own service (cc-tmux), not under the agent: a
# gateway restart (every switch, including the hourly upgrade) killed jobs
# whose tmux lived in hermes-agent's cgroup. A switch doesn't restart it either.
{ config, lib, pkgs, ... }:
let
  cfg = config.services.hermes-agent;
  sock = "/run/cc-tmux/sock";
  tmux = "${pkgs.tmux}/bin/tmux -S ${sock}";

  cc = pkgs.writeShellApplication {
    name = "cc";
    runtimeInputs = with pkgs; [
      tmux
      jq
      coreutils
      gnugrep
      gnused
    ];
    text = ''
      usage() {
        cat >&2 <<'EOF'
      cc start <name> <dir> <task-file>   start a job; prints its tmux session and claude.ai URL
      cc send <session> <message>         type a message into a running job
      cc peek <session> [lines]           the job's screen, last N non-empty lines (default 40)
      cc list                             running jobs
      cc stop <session>                   end a job
      EOF
        exit 2
      }

      tmux() { command tmux -S ${sock} "$@"; }
      slug() { printf '%s' "$1" | tr '[:upper:]' '[:lower:]' | sed -E 's/[^a-z0-9]+/-/g; s/^-+|-+$//g'; }

      cmd=''${1:-}
      shift || true
      case "$cmd" in
        start)
          [ $# -eq 3 ] || usage
          name=$1
          dir=$(realpath "$2")
          task=$(cat "$3")
          s=$(slug "$name")
          if tmux has-session -t "=$s" 2>/dev/null; then
            echo "cc: a job named $s is already running" >&2
            exit 1
          fi
          # Trust the folder up front: the trust dialog would otherwise wait for a keypress.
          conf="$HOME/.claude.json"
          [ -f "$conf" ] || echo '{}' >"$conf"
          tmp=$(mktemp "$conf.XXXXXX")
          jq --arg d "$dir" '.projects[$d].hasTrustDialogAccepted = true' "$conf" >"$tmp"
          chmod 600 "$tmp"
          mv "$tmp" "$conf"
          # The server's environment is the service's; pass the caller's non-secret basics.
          tmux new-session -d -s "$s" -x 200 -y 50 -c "$dir" \
            -e "PATH=$PATH" -e "HOME=$HOME" -e "TMPDIR=''${TMPDIR:-/tmp}" -e "LANG=''${LANG:-C.UTF-8}" \
            claude --remote-control "$name" "$task"
          # Keep the pane after claude exits, so its last screen can still be read.
          tmux set-option -t "$s" remain-on-exit on >/dev/null
          echo "session: $s"
          for _ in $(seq 1 30); do
            url=$(tmux capture-pane -p -J -t "$s" | grep -o 'https://claude.ai/code/session_[A-Za-z0-9]*' | head -1 || true)
            if [ -n "$url" ]; then
              echo "url: $url"
              exit 0
            fi
            sleep 1
          done
          echo "cc: no Remote Control URL after 30 s; check with: cc peek $s" >&2
          exit 1
          ;;
        send)
          [ $# -ge 2 ] || usage
          s=$1
          shift
          # One line: a newline would submit early.
          msg=$(printf '%s' "$*" | tr '\n' ' ')
          tmux send-keys -t "=$s:" C-u
          tmux send-keys -t "=$s:" -l "$msg"
          sleep 0.3
          tmux send-keys -t "=$s:" Enter
          ;;
        peek)
          [ $# -ge 1 ] || usage
          tmux capture-pane -p -J -t "=$1:" | grep -v '^[[:space:]]*$' | tail -n "''${2:-40}"
          ;;
        list)
          tmux list-sessions -F '#{session_name} #{?pane_dead,exited,running} since #{t:session_created}' 2>/dev/null | grep -v '^_keep ' || echo "no jobs"
          ;;
        stop)
          [ $# -eq 1 ] || usage
          tmux kill-session -t "=$1"
          ;;
        *) usage ;;
      esac
    '';
  };
in
{
  services.hermes-agent.extraPackages = [ cc ];

  systemd.services.cc-tmux = {
    description = "tmux server for the agent's Claude Code jobs (cc)";
    wantedBy = [ "multi-user.target" ];
    after = [ "network-online.target" ];
    wants = [ "network-online.target" ];
    # Updating the unit must not end running jobs; the new one applies on the next start.
    restartIfChanged = false;
    environment = {
      HOME = cfg.stateDir;
      PATH = lib.mkForce "/run/wrappers/bin:/etc/profiles/per-user/${cfg.user}/bin:/run/current-system/sw/bin";
    };
    serviceConfig = {
      User = cfg.user;
      Group = cfg.group;
      Type = "forking";
      RuntimeDirectory = "cc-tmux";
      RuntimeDirectoryMode = "0700";
      WorkingDirectory = cfg.stateDir;
      # A placeholder session keeps the server up with no jobs.
      ExecStart = "${tmux} new-session -d -s _keep ${pkgs.coreutils}/bin/sleep infinity";
      ExecStop = "${tmux} kill-server";
      Restart = "on-failure";
    };
  };
}
