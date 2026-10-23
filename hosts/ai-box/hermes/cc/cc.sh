# cc: the agent's Claude Code jobs as Remote Control sessions in tmux, so Alex
# can watch and steer them from claude.ai/code or the Claude app.
# Packaged by default.nix (writeShellApplication adds the shebang, strict mode
# and CC_TMUX_SOCK, the socket of the cc-tmux service's server).

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

tmux() { command tmux -S "$CC_TMUX_SOCK" "$@"; }
slug() { printf '%s' "$1" | tr '[:upper:]' '[:lower:]' | sed -E 's/[^a-z0-9]+/-/g; s/^-+|-+$//g'; }

cmd=${1:-}
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
      -e "PATH=$PATH" -e "HOME=$HOME" -e "TMPDIR=${TMPDIR:-/tmp}" -e "LANG=${LANG:-C.UTF-8}" \
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
    tmux capture-pane -p -J -t "=$1:" | grep -v '^[[:space:]]*$' | tail -n "${2:-40}"
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
