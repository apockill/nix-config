# cc: the agent's Claude Code jobs as Remote Control sessions in tmux, so Alex
# can watch and steer them from claude.ai/code or the Claude app.
# Packaged by default.nix (writeShellApplication adds the shebang, strict mode,
# CC_TMUX_SOCK, the socket of the cc-tmux service's server, and CC_JOBS, which
# holds each job's record from `cc start` until `cc stop`, so `cc restore`
# can resume it after a boot).

usage() {
  cat >&2 <<'EOF'
cc start <name> <dir> <task-file>   start a job; prints its tmux session and claude.ai URL
cc send <session> <message>         type a message into a running job
cc peek <session> [lines]           the job's screen, last N non-empty lines (default 40)
cc list                             running jobs
cc stop <session>                   end a job
cc restore                          resume recorded jobs that aren't running (run at boot)
EOF
  exit 2
}

tmux() { command tmux -S "$CC_TMUX_SOCK" "$@"; }
slug() { printf '%s' "$1" | tr '[:upper:]' '[:lower:]' | sed -E 's/[^a-z0-9]+/-/g; s/^-+|-+$//g'; }

# launch <session> <dir> <env-json> <claude args...>: run claude in a new tmux session.
launch() {
  local s=$1 dir=$2 envjson=$3
  shift 3
  # Trust the folder up front: the trust dialog would otherwise wait for a keypress.
  local conf="$HOME/.claude.json" tmp
  [ -f "$conf" ] || echo '{}' >"$conf"
  tmp=$(mktemp "$conf.XXXXXX")
  jq --arg d "$dir" '.projects[$d].hasTrustDialogAccepted = true' "$conf" >"$tmp"
  chmod 600 "$tmp"
  mv "$tmp" "$conf"
  local envargs=()
  mapfile -t envargs < <(jq -r '.[] | "-e", .' <<<"$envjson")
  tmux new-session -d -s "$s" -x 200 -y 50 -c "$dir" "${envargs[@]}" claude "$@"
  # Keep the pane after claude exits, so its last screen can still be read.
  tmux set-option -t "$s" remain-on-exit on >/dev/null
}

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
    id=$(cat /proc/sys/kernel/random/uuid)
    # The server's environment is the service's; pass the caller's non-secret basics.
    env=$(jq -n --arg path "$PATH" --arg home "$HOME" --arg tmp "${TMPDIR:-/tmp}" --arg lang "${LANG:-C.UTF-8}" \
      '["PATH=\($path)", "HOME=\($home)", "TMPDIR=\($tmp)", "LANG=\($lang)"]')
    mkdir -p "$CC_JOBS"
    jq -n --arg name "$name" --arg dir "$dir" --arg id "$id" --argjson env "$env" \
      '{name: $name, dir: $dir, session_id: $id, env: $env}' >"$CC_JOBS/$s.json"
    launch "$s" "$dir" "$env" --remote-control "$name" --session-id "$id" "$task"
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
    rm -f "$CC_JOBS/$1.json"
    tmux kill-session -t "=$1"
    ;;
  restore)
    [ $# -eq 0 ] || usage
    for f in "$CC_JOBS"/*.json; do
      [ -e "$f" ] || continue
      s=$(basename "$f" .json)
      tmux has-session -t "=$s" 2>/dev/null && continue
      job=$(cat "$f")
      launch "$s" "$(jq -r .dir <<<"$job")" "$(jq -c .env <<<"$job")" \
        --remote-control "$(jq -r .name <<<"$job")" --resume "$(jq -r .session_id <<<"$job")"
      echo "restored: $s"
    done
    ;;
  *) usage ;;
esac
