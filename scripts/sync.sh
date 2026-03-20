#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────────
# sync.sh — Periodic sync from GitHub and rebuild if changes detected
#
# Designed to run as a cron job on the VPS:
#   * * * * * /opt/rv-energy/scripts/sync.sh >> /var/log/rv-energy-sync.log 2>&1
# ─────────────────────────────────────────────────────────────────────────────
set -euo pipefail

DEPLOY_DIR="/opt/rv-energy"
BRANCH="main"

cd "$DEPLOY_DIR"

# Fetch remote without merging
git fetch origin "$BRANCH" --quiet

LOCAL=$(git rev-parse HEAD)
REMOTE=$(git rev-parse "origin/$BRANCH")

if [[ "$LOCAL" == "$REMOTE" ]]; then
  # No changes — exit silently (cron log stays clean)
  exit 0
fi

echo "[$(date '+%Y-%m-%d %H:%M:%S')] New commits detected: ${LOCAL:0:7} → ${REMOTE:0:7}"

echo "[$(date '+%Y-%m-%d %H:%M:%S')] Pulling changes..."
git pull origin "$BRANCH"

echo "[$(date '+%Y-%m-%d %H:%M:%S')] Rebuilding and restarting container..."
docker compose up --build -d

echo "[$(date '+%Y-%m-%d %H:%M:%S')] Cleaning up dangling images..."
docker image prune -f

echo "[$(date '+%Y-%m-%d %H:%M:%S')] Deploy complete."
