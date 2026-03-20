# ─────────────────────────────────────────────────────────────────────────────
# RV Energy Intelligence v2.1 — Dockerfile
# Elevatics AI
# ─────────────────────────────────────────────────────────────────────────────

FROM python:3.11-slim AS base

LABEL maintainer="Elevatics AI <hello@elevatics.ai>"
LABEL description="RV Energy Intelligence — FastAPI + SQLite"
LABEL version="2.1.0"

WORKDIR /app

# ── System dependencies ───────────────────────────────────────────────────────
RUN apt-get update && apt-get install -y --no-install-recommends \
    sqlite3 \
    git \
    cron \
    && rm -rf /var/lib/apt/lists/*

# ── Python dependencies ───────────────────────────────────────────────────────
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# ── Application code ──────────────────────────────────────────────────────────
COPY . .

RUN mkdir -p data static

# ── Cron job: git pull every minute ──────────────────────────────────────────
RUN echo "* * * * * cd /app && git pull origin main >> /var/log/sync.log 2>&1" \
    | crontab -

# ── Runtime configuration ─────────────────────────────────────────────────────
ENV HOST=0.0.0.0
ENV PORT=5000
ENV DEBUG=false
ENV DB_PATH=/app/data/rv_energy.db

EXPOSE 5000

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:5000/api/health')" || exit 1

# ── Entry point: start cron + uvicorn ────────────────────────────────────────
CMD ["bash", "scripts/start.sh"]
