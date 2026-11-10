#!/usr/bin/env bash
# Build and (re)start Voxa in Docker, with automatic rollback. No sudo needed after deploy/docker-setup.sh.
#   bash deploy/docker-deploy.sh            # from the app folder (e.g. ~/tts-studio)
set -euo pipefail
APP_DIR="$(cd "$(dirname "$0")/.." && pwd)"; cd "$APP_DIR"
[ "$APP_DIR" != "$HOME" ] || { echo "Refusing to run in \$HOME" >&2; exit 1; }
PORT=5057
DC() { if docker info >/dev/null 2>&1; then docker "$@"; else sg docker -c "docker $(printf '%q ' "$@")"; fi; }
log() { printf '\n== %s\n' "$*"; }

log "Code"
git fetch -q origin main && git reset -q --hard origin/main && git log --oneline -1
python3 scripts/stamp_build.py >/dev/null && cat build.json; echo

log "Settings (.env.docker, not in git)"
[ -f .secret_key ] || python3 -c "import secrets;print(secrets.token_hex(32))" > .secret_key
touch .env.docker; chmod 600 .env.docker
grep -q '^SECRET_KEY=' .env.docker || echo "SECRET_KEY=$(cat .secret_key)" >> .env.docker
grep -q '^COOKIE_SECURE=' .env.docker || echo "COOKIE_SECURE=1" >> .env.docker
mkdir -p data
export VOXA_UID="$(stat -c %u data)" VOXA_GID="$(stat -c %g data)"

log "Build image (first build takes a few minutes)"
DC compose -f deploy/docker-compose.server.yml build

log "Switch over"
# stop the non-Docker app (venv + gunicorn) and its watchdog, if they are running
XDG_RUNTIME_DIR="${XDG_RUNTIME_DIR:-/run/user/$(id -u)}" systemctl --user disable --now voiceforge-watchdog.timer 2>/dev/null || true
for pid in $(pgrep -f "gunicorn.*127.0.0.1:$PORT" || true); do kill "$pid" 2>/dev/null || true; done
sleep 2
DC compose -f deploy/docker-compose.server.yml up -d --remove-orphans
ok=0
for i in $(seq 1 60); do curl -fs -m 3 "http://127.0.0.1:$PORT/healthz" >/dev/null && { ok=1; break; }; sleep 2; done
if [ "$ok" = 1 ]; then
  curl -fs "http://127.0.0.1:$PORT/api/config" | grep -o '"build":{[^}]*}'
  DC image prune -f >/dev/null || true
  echo "Voxa is running in Docker (container 'voxa', restarts automatically)."
else
  echo "Container did not become healthy - rolling back to the previous (non-Docker) setup." >&2
  DC compose -f deploy/docker-compose.server.yml logs --tail 40 >&2 || true
  DC compose -f deploy/docker-compose.server.yml down || true
  SKIP_PULL=1 bash deploy/update.sh >/dev/null 2>&1 || true
  exit 1
fi
