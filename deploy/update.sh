#!/usr/bin/env bash
# One-command update for a VoiceForge server without root (venv + gunicorn + Cloudflare quick tunnel).
#   bash deploy/update.sh                 # pull, install, stamp build, restart, keep tunnel
#   WITH_OFFICE=1 bash deploy/update.sh   # also install a portable LibreOffice (Word/Excel/PPT import), ~350 MB
# SKIP_TUNNEL=1 leaves the public link alone. Settings (env): APP_DIR (default: repo root), PORT (5057), VF_DATA (APP_DIR/data), WORKERS (2)
set -euo pipefail
APP_DIR="${APP_DIR:-$(cd "$(dirname "$0")/.." && pwd)}"
PORT="${PORT:-5057}"; WORKERS="${WORKERS:-2}"
export VF_DATA="${VF_DATA:-$APP_DIR/data}"
cd "$APP_DIR"
log() { printf '\n== %s\n' "$*"; }

log "Updating code"
REPO="${REPO:-https://github.com/zubypk/voiceforge}"
if [ "${SKIP_PULL:-0}" = "1" ]; then echo "(pull skipped)"
elif [ ! -d .git ]; then   # turn an existing copied folder into a checkout; venv/, data/, .secret_key are git-ignored and kept
  git init -q && git remote add origin "$REPO"
  git fetch -q origin main && git reset -q --hard origin/main
else
  [ -f .git/shallow ] && git fetch -q --unshallow origin || true
  git pull -q --ff-only
fi
git log --oneline -1 2>/dev/null || true

log "Python packages"
[ -x venv/bin/python ] || python3 -m venv venv
venv/bin/pip install -q --upgrade pip >/dev/null
venv/bin/pip install -q -r requirements.txt

if [ "${WITH_OFFICE:-0}" = "1" ] && [ ! -x "$HOME/opt/libreoffice/program/soffice" ]; then
  log "Installing portable LibreOffice in ~/opt/libreoffice (no root needed)"
  base=https://download.documentfoundation.org/libreoffice/stable
  ver=$(curl -fsSL "$base/" | grep -oE 'href="[0-9]+\.[0-9]+\.[0-9]+/' | grep -oE '[0-9]+\.[0-9]+\.[0-9]+' | sort -V | tail -1)
  tmp=$(mktemp -d)
  curl -fL --retry 3 -o "$tmp/lo.tgz" "$base/$ver/deb/x86_64/LibreOffice_${ver}_Linux_x86-64_deb.tar.gz"
  tar -xzf "$tmp/lo.tgz" -C "$tmp"
  mkdir -p "$tmp/root"
  for d in "$tmp"/LibreOffice_*/DEBS/*.deb; do dpkg-deb -x "$d" "$tmp/root"; done
  mkdir -p "$HOME/opt"; rm -rf "$HOME/opt/libreoffice"
  mv "$tmp"/root/opt/libreoffice* "$HOME/opt/libreoffice"; rm -rf "$tmp"
  "$HOME/opt/libreoffice/program/soffice" --version || echo "WARNING: LibreOffice installed but does not start (missing system libraries?)"
fi
if [ -x "$HOME/opt/libreoffice/program/soffice" ]; then export VF_SOFFICE="$HOME/opt/libreoffice/program/soffice"; fi

log "Build stamp"
venv/bin/python scripts/stamp_build.py

log "Restarting the app on 127.0.0.1:$PORT"
[ -f .secret_key ] || venv/bin/python -c "import secrets;print(secrets.token_hex(32))" > .secret_key
# stop only the gunicorn processes of THIS app (matched by bind address), never their parents
for pid in $(pgrep -f "gunicorn.*127.0.0.1:$PORT" || true); do
  if [ "$(cat /proc/$pid/comm 2>/dev/null)" != "bash" ]; then kill "$pid" 2>/dev/null || true; fi
done
sleep 2
SECRET_KEY="$(cat .secret_key)" COOKIE_SECURE=1 setsid nohup venv/bin/gunicorn -w "$WORKERS" --threads 4 --timeout 600 \
  -b "127.0.0.1:$PORT" app:app > server.log 2>&1 < /dev/null &
for i in $(seq 1 20); do curl -fs "http://127.0.0.1:$PORT/healthz" >/dev/null && break; sleep 1; done
curl -fs "http://127.0.0.1:$PORT/api/config" | grep -o '"build":{[^}]*}' || { echo "App did not start, see server.log:"; tail -20 server.log; exit 1; }

if [ "${SKIP_TUNNEL:-0}" = "1" ]; then echo "Done (tunnel skipped)."; exit 0; fi
log "Public demo link"
if ! pgrep -f "cloudflared.*:$PORT" >/dev/null; then
  CF="$(command -v cloudflared || echo "$APP_DIR/cloudflared")"
  if [ ! -x "$CF" ]; then
    curl -fsSL -o "$APP_DIR/cloudflared" https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64
    chmod +x "$APP_DIR/cloudflared"; CF="$APP_DIR/cloudflared"
  fi
  setsid nohup "$CF" tunnel --no-autoupdate --url "http://127.0.0.1:$PORT" > tunnel.log 2>&1 < /dev/null &
  sleep 8
fi
grep -oE 'https://[a-z0-9-]+\.trycloudflare\.com' tunnel.log 2>/dev/null | tail -1 || echo "(tunnel URL not found yet: see tunnel.log)"
echo "Done."
