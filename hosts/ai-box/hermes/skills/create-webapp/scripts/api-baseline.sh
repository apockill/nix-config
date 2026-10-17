#!/usr/bin/env bash
# Snapshot or compare an app's GET endpoints (status code + JSON key shape) over app.sock.
# usage: api-baseline.sh snap  <app> <dir> /api/health /api/live ...   # write baseline
#        api-baseline.sh check <app> <dir>                             # compare, exit 1 on diff
# Files: <dir>/<app>_<path with / -> _>.json (sorted keys; first element's keys for arrays) + .json.code
# Note: the filename->path mapping turns every _ back into /, so avoid snapping paths with underscores.
mode=$1; app=$2; dir=$3; shift 3
S=/var/lib/hermes/sites/$app/app.sock
shape() { jq -c 'if type=="array" then (.[0]//{}|keys) elif type=="object" then keys else empty end' 2>/dev/null; }
get() { curl -s -w '\n%{http_code}' --unix-socket "$S" "http://localhost$1"; }
printf 'UI /: '; curl -s -o /dev/null -w '%{http_code}\n' --unix-socket "$S" http://localhost/
if [[ $mode == snap ]]; then
  mkdir -p "$dir"
  for p in "$@"; do out=$(get "$p"); f="$dir/${app}${p//\//_}.json"
    printf '%s' "${out%$'\n'*}" | shape > "$f"; printf '%s' "${out##*$'\n'}" > "$f.code"; echo "snap $p ${out##*$'\n'}"; done
  exit 0
fi
fail=0
for c in "$dir"/${app}_*.json.code; do
  f=${c%.code}; rest=$(basename "$f" .json); rest=${rest#${app}_}; p="/${rest//_//}"
  out=$(get "$p"); code=${out##*$'\n'}; sh=$(printf '%s' "${out%$'\n'*}" | shape)
  if [[ $code == "$(cat "$c")" && $sh == "$(cat "$f")" ]]; then echo "OK   $p $code"
  else echo "DIFF $p code $(cat "$c")->$code shape $([[ $sh == "$(cat "$f")" ]] && echo same || echo changed)"; fail=1; fi
done
exit $fail
