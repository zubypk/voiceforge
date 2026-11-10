#!/usr/bin/env bash
# Publish VoiceForge on your own (sub)domain with HTTPS. Run ONCE with sudo, after the DNS record exists:
#   sudo bash deploy/nginx-site.sh studio.lusona.org [port] [email]
# Creates /etc/nginx/sites-available/<domain> (reverse proxy to 127.0.0.1:<port>, default 5057),
# enables it, checks the nginx config, reloads nginx and gets a Let's Encrypt certificate with certbot.
set -euo pipefail
DOMAIN="${1:?usage: sudo bash deploy/nginx-site.sh <domain> [port] [email]}"; PORT="${2:-5057}"; EMAIL="${3:-}"
[ "$(id -u)" = 0 ] || { echo "Run with sudo." >&2; exit 1; }
[[ "$DOMAIN" =~ ^[a-z0-9.-]+$ ]] || { echo "Invalid domain: $DOMAIN" >&2; exit 1; }
CONF="/etc/nginx/sites-available/$DOMAIN"
if [ -e "$CONF" ]; then echo "$CONF already exists: leaving it unchanged."; else
cat > "$CONF" <<NGINX
# VoiceForge -> 127.0.0.1:$PORT  (created by deploy/nginx-site.sh)
server {
    listen 80;
    listen [::]:80;
    server_name $DOMAIN;

    client_max_body_size 460m;          # video uploads, project bundles, audio editor exports
    proxy_read_timeout 900s;            # long renders / conversions
    proxy_send_timeout 900s;

    location / {
        proxy_pass http://127.0.0.1:$PORT;
        proxy_http_version 1.1;
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
        proxy_buffering off;
    }
}
NGINX
fi
ln -sf "$CONF" "/etc/nginx/sites-enabled/$DOMAIN"
nginx -t
systemctl reload nginx
echo "nginx is serving http://$DOMAIN"
if command -v certbot >/dev/null; then
  if [ -n "$EMAIL" ]; then certbot --nginx -d "$DOMAIN" --redirect --non-interactive --agree-tos -m "$EMAIL"
  else certbot --nginx -d "$DOMAIN" --redirect; fi
  echo "Done: https://$DOMAIN"
else
  echo "certbot is not installed: apt install certbot python3-certbot-nginx, then: certbot --nginx -d $DOMAIN --redirect"
fi
