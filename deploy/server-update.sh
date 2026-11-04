#!/usr/bin/env bash
# One-shot server update, run as root from any shell (fish too):
#
#   curl -fsSL https://raw.githubusercontent.com/<owner>/<repo>/<commit>/deploy/server-update.sh | sudo bash -s <commit>
#
# 0. checks everything first; puts back the code of an interrupted earlier run
# 1. installs the code of <commit> (downloaded from GitHub) into $APP, keeping a backup of the previous code
# 2. sets the upload / parse limits in the file the service reads (bf2view.env in the app folder, or $BF2VIEW_ENVFILE)
# 3. systemd drop-in: a parse child killed for memory no longer stops the whole service, swap capped, and the parse child may LOWER its own
#    memory limit (setrlimit; a hardened unit with SystemCallFilter=~@resources would kill it otherwise)
# 4. Caddy: the proxy's "Via" header is no longer sent to visitors (validated by the reload; restored if the reload fails)
# 5. restarts the service, then uploads a sample recording and waits until it is parsed INSIDE the service's sandbox;
#    on any failure the previous code, settings and drop-in are put back and the service restarted
# Running it twice is harmless.
set -euo pipefail

COMMIT=${1:?usage: server-update.sh <commit>}
REPO=${BF2VIEW_REPO:-Kakarotto22/bf2-replay-viewer}
BASE=${BF2VIEW_BASE:-/srv/bf2view}
APP=$BASE/app
SERVICE=${BF2VIEW_SERVICE:-bf2view}
UNIT_DIR=${BF2VIEW_UNIT_DIR:-/etc/systemd/system/$SERVICE.service.d}
DROPIN=$UNIT_DIR/parse-limits.conf
CADDY_FILE=${BF2VIEW_CADDY_FILE:-/etc/caddy/conf.d/bf2view.caddyfile}
PORT=${BF2VIEW_PORT:-18642}
BACKUPS=${BF2VIEW_BACKUPS:-/var/backups/bf2view}
SAMPLE_NAME=claude_spawn_115014.bf2demo

say() { printf '\033[1;36m== %s\033[0m\n' "$*"; }
die() { printf '\033[1;31m!! %s\033[0m\n' "$*" >&2; exit 1; }

# ------------------------------------------------------------------------------------------------ 0. checks, before anything changes
[[ $COMMIT =~ ^[0-9a-f]{7,40}$ ]] || die "the commit must be a hex id"
[ "$(id -u)" = 0 ] || die "run it with sudo"
[ -d "$APP/bf2demo" ] || [ -d "$APP/bf2demo.old" ] || die "$APP/bf2demo not found: is this the viewer's server?"
command -v systemctl >/dev/null || die "systemctl not found"
# the settings file: an explicit one, else bf2view.env in the app folder (read by wsgi.py and it OVERRIDES the unit's Environment= lines)
ENVFILE=${BF2VIEW_ENVFILE:-$APP/bf2view.env}
STAMP=$(date +%Y%m%d-%H%M%S)
WORK=$(mktemp -d)
trap 'rm -rf "$WORK"' EXIT
mkdir -p "$BACKUPS"

if [ -d "$APP/bf2demo.old" ]; then                     # an earlier run stopped half way: its "old" folder is the code that was running
  say "0/5 an interrupted earlier run left $APP/bf2demo.old: putting that code back first"
  rm -rf "$APP/bf2demo" && mv "$APP/bf2demo.old" "$APP/bf2demo"
fi

say "1/5 code $COMMIT"
curl -fsSL "https://codeload.github.com/$REPO/tar.gz/$COMMIT" -o "$WORK/src.tgz" || die "download failed"
tar xzf "$WORK/src.tgz" -C "$WORK" --no-same-owner
SRC=$(find "$WORK" -mindepth 1 -maxdepth 1 -type d | head -n1)
[ -f "$SRC/bf2demo/web/wsgi.py" ] || die "the download does not contain the viewer"
[ -f "$SRC/samples/$SAMPLE_NAME" ] || die "the download has no sample recording for the self test"
find "$SRC/bf2demo" -name '__pycache__' -prune -exec rm -rf {} +
tar czf "$BACKUPS/bf2demo-$STAMP.tgz" -C "$APP" bf2demo
[ -f "$ENVFILE" ] && cp -a "$ENVFILE" "$BACKUPS/env-$STAMP"
[ -f "$DROPIN" ] && cp -a "$DROPIN" "$BACKUPS/dropin-$STAMP"
rm -rf "$APP/bf2demo.new"
cp -a "$SRC/bf2demo" "$APP/bf2demo.new"
mkdir -p "$APP/deploy" && cp "$SRC/deploy/requirements-web.txt" "$APP/deploy/requirements-web.txt"
chown -R --reference="$APP" "$APP/bf2demo.new" "$APP/deploy"
mv "$APP/bf2demo" "$APP/bf2demo.old"
mv "$APP/bf2demo.new" "$APP/bf2demo"
echo "   previous code: $BACKUPS/bf2demo-$STAMP.tgz"

rollback() {
  printf '\033[1;31m!! %s: putting the previous code and settings back\033[0m\n' "$1" >&2
  if [ -d "$APP/bf2demo.old" ]; then rm -rf "$APP/bf2demo" && mv "$APP/bf2demo.old" "$APP/bf2demo"; fi
  if [ -f "$BACKUPS/env-$STAMP" ]; then cp -a "$BACKUPS/env-$STAMP" "$ENVFILE"; elif [ "${ENV_CREATED:-0}" = 1 ]; then rm -f "$ENVFILE"; fi
  if [ -f "$BACKUPS/dropin-$STAMP" ]; then cp -a "$BACKUPS/dropin-$STAMP" "$DROPIN"; else rm -f "$DROPIN"; fi
  systemctl daemon-reload
  systemctl restart "$SERVICE" || true
  journalctl -u "$SERVICE" -n 40 --no-pager || true
  exit 1
}

say "2/5 limits in $ENVFILE"
ENV_CREATED=0
if [ ! -f "$ENVFILE" ]; then
  ENV_CREATED=1
  printf '# settings of the viewer: they override the Environment= lines of the unit (see bf2demo/web/wsgi.py)\n' > "$ENVFILE"
  chown --reference="$APP" "$ENVFILE"; chmod 640 "$ENVFILE"
fi
set_key() {            # key value: replace the line of the key, or add it
  if grep -qE "^[[:space:]]*$1=" "$ENVFILE"; then sed -i -E "s|^[[:space:]]*$1=.*|$1=$2|" "$ENVFILE"; else printf '%s=%s\n' "$1" "$2" >> "$ENVFILE"; fi
}
add_key() {            # key value: only when the key is not set yet
  grep -qE "^[[:space:]]*$1=" "$ENVFILE" || printf '%s=%s\n' "$1" "$2" >> "$ENVFILE"
}
set_key BF2VIEW_MAX_UPLOAD_MB 95
set_key BF2VIEW_PARSE_MEMORY_MB 2000
set_key BF2VIEW_PARSE_TIMEOUT 600
add_key BF2VIEW_QUOTA_MB 20000            # public uploads need a cap on disk use (oldest upload goes first); an existing value is kept
grep -E '^BF2VIEW_' "$ENVFILE" | grep -viE 'DONATE|TOKEN|SECRET' | sed 's/^/   /'

say "3/5 systemd drop-in $DROPIN"
mkdir -p "$UNIT_DIR"
cat > "$DROPIN" <<'EOF'
[Service]
# a recording is parsed in a child process: if the kernel kills it for memory, only that parse fails (default "stop" takes the site down)
OOMPolicy=continue
MemorySwapMax=512M
# the parse child LOWERS its own address space limit (it can never raise it): allow just these two calls out of the blocked @resources group
SystemCallFilter=setrlimit prlimit64
EOF
systemctl daemon-reload

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

say "5/5 restart and self test"
URL="http://127.0.0.1:$PORT"
systemctl restart "$SERVICE"
up=0
for _ in $(seq 1 30); do
  body=$(curl -fsS -m 3 "$URL/api/game" 2>/dev/null) || body=""
  if [[ $body == *'"max_upload"'* ]]; then up=1; break; fi
  sleep 1
done
[ "$up" = 1 ] || rollback "the new code did not answer"
echo "   the service answers"

# a real recording, parsed by the real service: proves the child process starts and may set its limit inside the unit's sandbox
cp "$SRC/samples/$SAMPLE_NAME" "$WORK/bf2view_selftest.bf2demo"
reply=$(curl -sS -m 60 -F "file=@$WORK/bf2view_selftest.bf2demo" "$URL/api/upload" 2>&1) || reply=""
id=$(printf '%s' "$reply" | grep -oE '"id":"[0-9a-f]+"' | cut -d'"' -f4 || true)
if [ -z "$id" ]; then
  if [[ $reply == *rate_limited* || $reply == *http_403* ]]; then
    echo "   self test skipped (uploads are off or rate limited right now): the service answers with the new code"
    id=""
  else
    rollback "test upload refused: $reply"
  fi
fi
if [ -n "$id" ]; then
  state="parsing"
  for _ in $(seq 1 120); do
    code=$(curl -sS -m 10 -o "$WORK/doc" -w '%{http_code}' "$URL/api/demos/$id" 2>/dev/null) || code=000
    if [ "$code" = 200 ]; then state=ready; break; fi
    if grep -q '"status":"error"' "$WORK/doc" 2>/dev/null; then state="error $(grep -oE '"reason":"[a-z_]+"' "$WORK/doc")"; break; fi
    sleep 1
  done
  find "$BASE/cache/uploads" -maxdepth 1 -name 'bf2view_selftest_*.bf2demo' -delete 2>/dev/null || true
  [ "$state" = ready ] || rollback "the test recording was not parsed ($state)"
  echo "   a sample recording was uploaded and parsed by the service: OK (test file removed)"
fi

rm -rf "$APP/bf2demo.old"
say "done: the viewer runs $COMMIT"
