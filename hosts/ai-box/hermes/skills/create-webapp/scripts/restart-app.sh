#!/usr/bin/env bash
# Restart one app via the runner and wait until it is really back.
# usage: restart-app.sh <app> [timeout_s=480]
# Done = status.json shows a NEW pid AND status "up" (status alone can still read "up" from the old process).
app=$1; to=${2:-480}; ST=/var/lib/apps-health/status.json
cd /var/lib/hermes/sites || exit 2
old=$(jq -r ".apps.$app.pid" $ST); touch "$app/.runner.restart"; t0=$(date +%s)
while (( $(date +%s) - t0 < to )); do
  sleep 5; read -r p s < <(jq -r ".apps.$app|\"\(.pid) \(.status)\"" $ST)
  if [[ $p != "$old" && $s == up ]]; then echo "$app up: pid $old -> $p in $(( $(date +%s)-t0 ))s"; sleep 10; jq -c ".apps.$app" $ST; exit 0; fi
done
echo "$app NOT up after ${to}s: $(jq -c ".apps.$app" $ST)"; tail -5 "$app/app.log"; exit 1
