#!/usr/bin/env bash
# One-time Docker setup for Voxa. Run ONCE with sudo:   sudo bash deploy/docker-setup.sh [user]
#  - installs the "docker compose" plugin if missing
#  - adds the user (default: the one who ran sudo) to the docker group so deploy/docker-deploy.sh works without sudo
# NOTE: members of the docker group can control Docker, which is equivalent to root access on this server.
set -euo pipefail
[ "$(id -u)" = 0 ] || { echo "Run with sudo." >&2; exit 1; }
U="${1:-${SUDO_USER:-}}"; [ -n "$U" ] || { echo "usage: sudo bash deploy/docker-setup.sh <user>" >&2; exit 1; }
command -v docker >/dev/null || { echo "Docker is not installed (see https://docs.docker.com/engine/install/ubuntu/)." >&2; exit 1; }
if ! docker compose version >/dev/null 2>&1; then
  apt-get update -qq
  apt-get install -y docker-compose-v2 || apt-get install -y docker-compose-plugin
fi
docker compose version
getent group docker >/dev/null || groupadd docker
usermod -aG docker "$U"
systemctl is-enabled docker >/dev/null 2>&1 || systemctl enable --now docker
echo "Done. '$U' can now use Docker (new logins pick up the group; 'sg docker -c ...' works immediately)."
