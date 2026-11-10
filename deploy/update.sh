#!/usr/bin/env bash
# One-command update for a Voxa server without root (venv + gunicorn + Cloudflare quick tunnel).
#   bash deploy/update.sh                 # pull, install, stamp build, restart, keep tunnel
#   WITH_OFFICE=1 bash deploy/update.sh   # also install a portable LibreOffice (Word/Excel/PPT import), ~350 MB
# SKIP_TUNNEL=1 leaves the public link alone. Settings (env): APP_DIR (default: repo root), PORT (5057), VF_DATA (APP_DIR/data), WORKERS (2)
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
# deploy/update.sh -> app folder is the parent; a copy saved anywhere else -> that folder itself
if [ -z "${APP_DIR:-}" ]; then
  if [ "$(basename "$HERE")" = "deploy" ]; then APP_DIR="$(dirname "$HERE")"; else APP_DIR="$HERE"; fi
fi
if [ "$APP_DIR" = "$HOME" ] || [ "$APP_DIR" = "/" ]; then
  echo "Refusing to install into $APP_DIR. Put the app in its own folder (e.g. ~/tts-studio) or set APP_DIR." >&2; exit 1
fi
PORT="${PORT:-5057}"; WORKERS="${WORKERS:-2}"
export VF_DATA="${VF_DATA:-$APP_DIR/data}"
cd "$APP_DIR"
log() { printf '\n== %s\n' "$*"; }

log "Updating code"
REPO="${REPO:-https://github.com/zubypk/voiceforge}"
if [ "${SKIP_PULL:-0}" = "1" ]; then echo "(pull skipped)"
else   # a deploy folder always mirrors origin/main; venv/, data/, .secret_key, logs are git-ignored and kept
  [ -d .git ] || git init -q
  git remote get-url origin >/dev/null 2>&1 || git remote add origin "$REPO"
  [ -f .git/shallow ] && git fetch -q --unshallow origin main || true
  git fetch -q origin main
  git checkout -q -B main origin/main 2>/dev/null || git reset -q --hard origin/main
  git reset -q --hard origin/main
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

[ -f "$APP_DIR/.no_tunnel" ] && SKIP_TUNNEL=1     # created when the site has its own domain (deploy/nginx-site.sh)
if [ "${SKIP_TUNNEL:-0}" = "1" ]; then
  echo "Tunnel skipped."
else
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
grep -oE 'https://[a-z0-9-]+\.trycloudflare\.com' tunnel.log 2>/dev/null | tail -1 > PUBLIC_URL.txt || true
echo "Demo link: $(cat PUBLIC_URL.txt 2>/dev/null || echo 'not found yet, see tunnel.log')"
fi

log "Auto-restart (every 5 minutes and after reboot)"
job="cd $APP_DIR && PORT=$PORT bash deploy/watchdog.sh >/dev/null 2>&1"
if command -v crontab >/dev/null && ( crontab -l 2>/dev/null | grep -v 'deploy/watchdog.sh'; echo "*/5 * * * * $job"; echo "@reboot sleep 30; $job" ) | crontab - 2>/dev/null; then
  echo "Installed in crontab."
else
  # no crontab permission: use a systemd user timer (needs lingering for after-reboot starts)
  export XDG_RUNTIME_DIR="${XDG_RUNTIME_DIR:-/run/user/$(id -u)}"
  D="$HOME/.config/systemd/user"; mkdir -p "$D"
  printf '[Unit]\nDescription=Voxa watchdog\n\n[Service]\nType=oneshot\nWorkingDirectory=%s\nEnvironment=PORT=%s\nExecStart=/bin/bash %s/deploy/watchdog.sh\nKillMode=process\n' \
    "$APP_DIR" "$PORT" "$APP_DIR" > "$D/voiceforge-watchdog.service"
  printf '[Unit]\nDescription=Run the Voxa watchdog at boot and every 5 minutes\n\n[Timer]\nOnBootSec=60\nOnUnitActiveSec=5min\nPersistent=true\n\n[Install]\nWantedBy=timers.target\n' > "$D/voiceforge-watchdog.timer"
  if systemctl --user daemon-reload 2>/dev/null && systemctl --user enable --now voiceforge-watchdog.timer 2>/dev/null; then
    echo "Installed as a systemd user timer."
    loginctl show-user "$(id -u)" -p Linger 2>/dev/null | grep -q yes || echo "Note: run 'sudo loginctl enable-linger $(whoami)' so it also starts after a reboot."
  else
    echo "Could not install a scheduler: run deploy/watchdog.sh periodically yourself."
  fi
fi
echo "The current demo link is always in $APP_DIR/PUBLIC_URL.txt"
echo "Done."
