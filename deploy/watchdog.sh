#!/usr/bin/env bash
# Keeps Voxa and its public demo link alive. Installed into the user's crontab by update.sh:
#   */5 * * * *  and  @reboot   ->  bash deploy/watchdog.sh
# Restarts the app if /healthz stops answering and the Cloudflare quick tunnel if it is gone.
# The current public link is always written to PUBLIC_URL.txt in the app folder.
APP_DIR="${APP_DIR:-$(cd "$(dirname "$0")/.." && pwd)}"
[ "$APP_DIR" = "$HOME" ] && { echo "refusing to run in \$HOME" >&2; exit 1; }
PORT="${PORT:-5057}"; WORKERS="${WORKERS:-2}"
cd "$APP_DIR" || exit 1
export VF_DATA="${VF_DATA:-$APP_DIR/data}"
[ -x "$HOME/opt/libreoffice/program/soffice" ] && export VF_SOFFICE="$HOME/opt/libreoffice/program/soffice"
ts() { date '+%F %T'; }

if ! curl -fs -m 10 "http://127.0.0.1:$PORT/healthz" >/dev/null; then
  echo "$(ts) app down -> starting" >> watchdog.log
  for pid in $(pgrep -f "gunicorn.*127.0.0.1:$PORT" || true); do kill "$pid" 2>/dev/null || true; done
  sleep 2
  SECRET_KEY="$(cat .secret_key)" COOKIE_SECURE=1 setsid nohup venv/bin/gunicorn -w "$WORKERS" --threads 4 --timeout 600 \
    -b "127.0.0.1:$PORT" app:app >> server.log 2>&1 < /dev/null &
fi

[ -f "$APP_DIR/.no_tunnel" ] && SKIP_TUNNEL=1     # site has its own domain: no quick tunnel
if [ "${SKIP_TUNNEL:-0}" != "1" ] && ! pgrep -f "cloudflared.*:$PORT" >/dev/null; then
  CF="$(command -v cloudflared || echo "$APP_DIR/cloudflared")"
  if [ -x "$CF" ]; then
    echo "$(ts) tunnel down -> starting" >> watchdog.log
    setsid nohup "$CF" tunnel --no-autoupdate --url "http://127.0.0.1:$PORT" > tunnel.log 2>&1 < /dev/null &
    sleep 10
  fi
fi
url=$(grep -oE 'https://[a-z0-9-]+\.trycloudflare\.com' tunnel.log 2>/dev/null | tail -1)
[ -n "$url" ] && [ "$url" != "$(cat PUBLIC_URL.txt 2>/dev/null)" ] && { echo "$url" > PUBLIC_URL.txt; echo "$(ts) public link: $url" >> watchdog.log; }
exit 0
