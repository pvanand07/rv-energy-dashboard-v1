#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────────
# VPS First-Time Setup — RV Energy Intelligence
#
# Run once on a fresh VPS (Ubuntu/Debian):
#   scp scripts/vps-setup.sh user@vps:~
#   ssh user@vps bash vps-setup.sh
# ─────────────────────────────────────────────────────────────────────────────
set -euo pipefail

DEPLOY_DIR="/opt/rv-energy"
REPO_URL="${REPO_URL:-}"   # e.g. https://github.com/yourorg/rv-energy.git

if [[ -z "$REPO_URL" ]]; then
  echo "ERROR: Set REPO_URL before running. Example:"
  echo "  REPO_URL=https://github.com/yourorg/rv-energy.git bash vps-setup.sh"
  exit 1
fi

echo "==> Installing Docker..."
if ! command -v docker &>/dev/null; then
  curl -fsSL https://get.docker.com | sh
  sudo usermod -aG docker "$USER"
  echo "NOTE: Log out and back in for docker group to take effect, then re-run this script."
  exit 0
fi

echo "==> Installing Docker Compose plugin..."
if ! docker compose version &>/dev/null 2>&1; then
  sudo apt-get update && sudo apt-get install -y docker-compose-plugin
fi

echo "==> Installing git..."
if ! command -v git &>/dev/null; then
  sudo apt-get update && sudo apt-get install -y git
fi

echo "==> Cloning repo to $DEPLOY_DIR..."
if [[ -d "$DEPLOY_DIR/.git" ]]; then
  echo "   Already cloned, pulling latest..."
  git -C "$DEPLOY_DIR" pull origin main
else
  sudo git clone "$REPO_URL" "$DEPLOY_DIR"
  sudo chown -R "$USER:$USER" "$DEPLOY_DIR"
fi

echo "==> Building and starting container..."
cd "$DEPLOY_DIR"
docker compose up --build -d

echo ""
echo "Done. App running at http://$(curl -s ifconfig.me 2>/dev/null || echo '<VPS_IP>'):5000"
echo ""
echo "Future deploys are handled automatically via GitHub Actions on push to main."
