#!/usr/bin/env bash
# One-shot server update, run as root from any shell (fish too):
#
#   curl -fsSL https://raw.githubusercontent.com/<owner>/<repo>/<commit>/deploy/server-update.sh | sudo bash -s <commit>
#
# 1. installs the code of <commit> (downloaded from GitHub) into $APP, keeping a backup of the previous code
# 2. sets the upload / parse limits in the service's env file (only the keys below, other lines untouched)
# 3. systemd drop-in: a parse child killed for memory no longer stops the whole service; swap of the service capped
# 4. Caddy: the proxy's "Via" header is no longer sent to visitors (validated by the reload; restored if the reload fails)
# 5. restarts the service and checks it answers; on failure the previous code is put back and restarted
# Running it twice is harmless.
set -euo pipefail

COMMIT=${1:?usage: server-update.sh <commit>}
REPO=${BF2VIEW_REPO:-Kakarotto22/bf2-replay-viewer}
BASE=${BF2VIEW_BASE:-/srv/bf2view}
APP=$BASE/app
ENVFILE=${BF2VIEW_ENVFILE:-$BASE/env}
SERVICE=${BF2VIEW_SERVICE:-bf2view}
UNIT_DIR=${BF2VIEW_UNIT_DIR:-/etc/systemd/system/$SERVICE.service.d}
CADDY_FILE=${BF2VIEW_CADDY_FILE:-/etc/caddy/conf.d/bf2view.caddyfile}
PORT=${BF2VIEW_PORT:-18642}
BACKUPS=${BF2VIEW_BACKUPS:-/var/backups/bf2view}

say() { printf '\033[1;36m== %s\033[0m\n' "$*"; }
die() { printf '\033[1;31m!! %s\033[0m\n' "$*" >&2; exit 1; }

[[ $COMMIT =~ ^[0-9a-f]{7,40}$ ]] || die "the commit must be a hex id"
[ -d "$APP/bf2demo" ] || die "$APP/bf2demo not found: is this the viewer's server?"
STAMP=$(date +%Y%m%d-%H%M%S)
WORK=$(mktemp -d)
trap 'rm -rf "$WORK"' EXIT

say "1/5 code $COMMIT"
curl -fsSL "https://codeload.github.com/$REPO/tar.gz/$COMMIT" -o "$WORK/src.tgz" || die "download failed"
tar xzf "$WORK/src.tgz" -C "$WORK" --no-same-owner
SRC=$(find "$WORK" -mindepth 1 -maxdepth 1 -type d | head -n1)
[ -f "$SRC/bf2demo/web/wsgi.py" ] || die "the download does not contain the viewer"
find "$SRC/bf2demo" -name '__pycache__' -prune -exec rm -rf {} +
mkdir -p "$BACKUPS"
tar czf "$BACKUPS/bf2demo-$STAMP.tgz" -C "$APP" bf2demo
rm -rf "$APP/bf2demo.new" "$APP/bf2demo.old"
cp -a "$SRC/bf2demo" "$APP/bf2demo.new"
mkdir -p "$APP/deploy" && cp "$SRC/deploy/requirements-web.txt" "$APP/deploy/requirements-web.txt"
chown -R --reference="$APP" "$APP/bf2demo.new" "$APP/deploy"
mv "$APP/bf2demo" "$APP/bf2demo.old"
mv "$APP/bf2demo.new" "$APP/bf2demo"
echo "   previous code: $BACKUPS/bf2demo-$STAMP.tgz"

say "2/5 limits in $ENVFILE"
set_key() {            # file key value: replace the line of the key, or add it
  local file=$1 key=$2 value=$3
  if grep -qE "^[[:space:]]*$key=" "$file"; then sed -i -E "s|^[[:space:]]*$key=.*|$key=$value|" "$file"; else printf '%s=%s\n' "$key" "$value" >> "$file"; fi
}
add_key() {            # file key value: only when the key is not set yet
  grep -qE "^[[:space:]]*$2=" "$1" || printf '%s=%s\n' "$2" "$3" >> "$1"
}
[ -f "$ENVFILE" ] || die "$ENVFILE not found"
cp -a "$ENVFILE" "$BACKUPS/env-$STAMP"
for f in "$ENVFILE" "$APP/bf2view.env"; do          # bf2view.env in the app folder overrides the env file: keep both in step
  [ -f "$f" ] || continue
  set_key "$f" BF2VIEW_MAX_UPLOAD_MB 95
  set_key "$f" BF2VIEW_PARSE_MEMORY_MB 2000
  set_key "$f" BF2VIEW_PARSE_TIMEOUT 600
done
add_key "$ENVFILE" BF2VIEW_QUOTA_MB 20000            # public uploads need a cap on disk use (oldest upload goes first); an existing value is kept
grep -E '^BF2VIEW_(MAX_UPLOAD_MB|PARSE_MEMORY_MB|PARSE_TIMEOUT|QUOTA_MB|UPLOAD)=' "$ENVFILE" | sed 's/^/   /'

say "3/5 systemd drop-in"
mkdir -p "$UNIT_DIR"
cat > "$UNIT_DIR/parse-limits.conf" <<'EOF'
[Service]
# a recording is parsed in a child process: if the kernel kills it for memory, only that parse fails (default "stop" takes the site down)
OOMPolicy=continue
MemorySwapMax=512M
EOF
command -v systemctl >/dev/null && systemctl daemon-reload

say "4/5 caddy"
if [ -f "$CADDY_FILE" ]; then
  if grep -q 'header_down -Via' "$CADDY_FILE"; then
    echo "   already done"
  elif grep -qE "^[[:space:]]*reverse_proxy[[:space:]]+[^{]*:$PORT[[:space:]]*$" "$CADDY_FILE"; then
    cp -a "$CADDY_FILE" "$BACKUPS/caddy-$STAMP"
    sed -i -E "s|^([[:space:]]*)(reverse_proxy[[:space:]]+[^{]*:$PORT)[[:space:]]*$|\1\2 {\n\1\theader_down -Via\n\1}|" "$CADDY_FILE"
    if systemctl reload caddy; then echo "   Via header removed"; else
      cp -a "$BACKUPS/caddy-$STAMP" "$CADDY_FILE"; systemctl reload caddy || true
      echo "   caddy refused the change: file restored, nothing else affected"
    fi
  else
    echo "   reverse_proxy line has another form: left as it is"
  fi
else
  echo "   $CADDY_FILE not found: skipped"
fi

say "5/5 restart and check"
check() {
  for _ in $(seq 1 30); do
    local body; body=$(curl -fsS -m 3 "http://127.0.0.1:$PORT/api/game" 2>/dev/null) || body=""
    [[ $body == *'"max_upload"'* ]] && return 0
    sleep 1
  done
  return 1
}
systemctl restart "$SERVICE"
if check; then
  rm -rf "$APP/bf2demo.old"
  systemctl is-active "$SERVICE" >/dev/null && say "done: the viewer runs the new code ($(curl -fsS -m 3 "http://127.0.0.1:$PORT/api/game" | grep -o '"max_upload":[0-9]*'))"
else
  printf '\033[1;31m!! the new code did not answer: putting the previous code back\033[0m\n' >&2
  rm -rf "$APP/bf2demo" && mv "$APP/bf2demo.old" "$APP/bf2demo"
  cp -a "$BACKUPS/env-$STAMP" "$ENVFILE"
  systemctl restart "$SERVICE"
  journalctl -u "$SERVICE" -n 30 --no-pager || true
  exit 1
fi
