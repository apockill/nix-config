# gh-app-token: print a 1-hour installation token for the ailex-bot GitHub App (apockill's repos).
# The private key is read from 1Password (vault ai-assistant, item "GitHub App", field credential)
# straight into openssl through a pipe; it never touches disk, argv or the environment.
# Use:  GH_TOKEN=$(gh-app-token) gh pr create ...   (the token itself must never be printed)
ITEM=dwtnqynocxisqjlymzho6okqrq
APP_ID=5685960
OWNER=${1:-apockill}
OPENSSL=openssl
b64url() { "$OPENSSL" base64 -A | tr '+/' '-_' | tr -d '='; }
now=$(date +%s)
h=$(printf '{"alg":"RS256","typ":"JWT"}' | b64url)
p=$(printf '{"iat":%d,"exp":%d,"iss":"%s"}' $((now - 60)) $((now + 540)) "$APP_ID" | b64url)
key() { op item get "$ITEM" --vault ai-assistant --fields label=credential --reveal | sed 's/^"//; s/"$//'; }
sig=$(printf '%s.%s' "$h" "$p" | "$OPENSSL" dgst -sha256 -sign <(key) | b64url)
jwt="$h.$p.$sig"
api() { curl -fsS -H "Authorization: Bearer $jwt" -H "Accept: application/vnd.github+json" "$@"; }
inst=$(api https://api.github.com/app/installations | jq -r --arg o "$OWNER" '.[] | select(.account.login == $o) | .id')
[ -n "$inst" ] || { echo "gh-app-token: no installation on $OWNER" >&2; exit 1; }
api -X POST "https://api.github.com/app/installations/$inst/access_tokens" | jq -r .token
