#!/usr/bin/env bash
# Push the viewer from your PC to the server (run it in Git Bash / WSL / Linux from anywhere inside the repo).
#
#   deploy/publish.sh deploy@server.example.com [DEMOS_DIR] [--no-assets]
#
#   - the code (the bf2demo package, without tests, samples, re_work, extracted_bin, .claude ...) goes to $DEST/app
#   - DEMOS_DIR (optional): only the *.bf2demo files in that folder go to $DEST/demos (they hold real player names: publish what you choose)
#   - the viewer's game asset store and map backdrops (<cache>/game, <cache>/maps) go to $DEST/cache unless --no-assets is given
#     (they are the game's own icons, fonts and minimaps: keep the site behind a password, or leave them out)
# Nothing else leaves your machine. Needs: ssh access, tar. The service is restarted at the end when sudo allows it.
set -euo pipefail

HOST=${1:?usage: deploy/publish.sh user@server [demos-dir] [--no-assets]}
DEMOS=${2:-}
[ "$DEMOS" = "--no-assets" ] && { DEMOS=""; NO_ASSETS=1; }
NO_ASSETS=${NO_ASSETS:-0}
[ "${3:-}" = "--no-assets" ] && NO_ASSETS=1
DEST=${BF2VIEW_DEST:-/srv/bf2view}
CACHE=${BF2VIEW_LOCAL_CACHE:-$HOME/.bf2demo-viewer-cache}

cd "$(dirname "$0")/.."

echo "== code -> $HOST:$DEST/app"
tar czf - --exclude='__pycache__' --exclude='*.pyc' bf2demo deploy/requirements-web.txt \
  | ssh "$HOST" "mkdir -p '$DEST/app' && tar xzf - -C '$DEST/app'"

if [ -n "$DEMOS" ]; then
  echo "== recordings from $DEMOS -> $HOST:$DEST/demos"
  ( cd "$DEMOS" && tar czf - --wildcards '*.bf2demo' ) | ssh "$HOST" "mkdir -p '$DEST/demos' && tar xzf - -C '$DEST/demos'"
fi

if [ "$NO_ASSETS" = 0 ] && [ -d "$CACHE/game" ]; then
  echo "== asset store -> $HOST:$DEST/cache"
  ( cd "$CACHE" && tar czf - game $( [ -d maps ] && echo maps ) ) | ssh "$HOST" "mkdir -p '$DEST/cache' && tar xzf - -C '$DEST/cache'"
fi

echo "== restart"
ssh "$HOST" "sudo -n systemctl restart bf2view && systemctl is-active bf2view" \
  || echo "(could not restart the service: run  sudo systemctl restart bf2view  on the server)"
echo "done"
