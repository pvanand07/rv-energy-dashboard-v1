#!/bin/bash
set -e

LOG=/var/log/sync.log

echo "[$(date '+%Y-%m-%d %H:%M:%S')] Container starting..." | tee -a "$LOG"

# When `/app` is bind-mounted from the host, Git may refuse to operate due to
# "dubious ownership". Mark it as safe so cron + git commands can sync.
git config --global --add safe.directory /app >/dev/null 2>&1 || true

# Verify git is available and repo is intact
echo "[$(date '+%Y-%m-%d %H:%M:%S')] Git version: $(git --version)" | tee -a "$LOG"
echo "[$(date '+%Y-%m-%d %H:%M:%S')] Working dir: $(pwd)" | tee -a "$LOG"
echo "[$(date '+%Y-%m-%d %H:%M:%S')] Git remote: $(git remote get-url origin 2>&1 || true)" | tee -a "$LOG"
echo "[$(date '+%Y-%m-%d %H:%M:%S')] Current commit: $(git rev-parse --short HEAD 2>&1 || true)" | tee -a "$LOG"

# Start cron
echo "[$(date '+%Y-%m-%d %H:%M:%S')] Starting cron..." | tee -a "$LOG"
service cron start
echo "[$(date '+%Y-%m-%d %H:%M:%S')] Cron status: $(service cron status 2>&1)" | tee -a "$LOG"

# Show registered crontab
echo "[$(date '+%Y-%m-%d %H:%M:%S')] Crontab: $(crontab -l 2>&1)" | tee -a "$LOG"

echo "[$(date '+%Y-%m-%d %H:%M:%S')] Starting uvicorn with --reload..." | tee -a "$LOG"
exec uvicorn main:app --host 0.0.0.0 --port 5000 --reload
