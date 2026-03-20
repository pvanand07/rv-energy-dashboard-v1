# ─────────────────────────────────────────────────────────────────────────────
# RV Energy Intelligence v2.1 — Dockerfile
# Elevatics AI
#
# Build:  docker build -t rv-energy .
# Run:    docker run -p 5000:5000 -v $(pwd)/data:/app/data rv-energy
# Dev:    docker run -p 5000:5000 -v $(pwd):/app rv-energy
# ─────────────────────────────────────────────────────────────────────────────

# ── Base image ───────────────────────────────────────────────────────────────
FROM python:3.11-slim AS base

LABEL maintainer="Elevatics AI <hello@elevatics.ai>"
LABEL description="RV Energy Intelligence — FastAPI + SQLite"
LABEL version="2.1.0"

# Set working directory
WORKDIR /app

# ── System dependencies ───────────────────────────────────────────────────────
# Only what's absolutely needed — keeps image small
RUN apt-get update && apt-get install -y --no-install-recommends \
    sqlite3 \
    && rm -rf /var/lib/apt/lists/*

# ── Python dependencies ───────────────────────────────────────────────────────
# Copy requirements first for better layer caching
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# ── Application code ──────────────────────────────────────────────────────────
COPY . .

# Create runtime directories
RUN mkdir -p data static

# ── Runtime configuration ─────────────────────────────────────────────────────
ENV HOST=0.0.0.0
ENV PORT=5000
ENV DEBUG=false
ENV DB_PATH=/app/data/rv_energy.db

# Expose port
EXPOSE 5000

# Health check (uses /api/health endpoint)
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:5000/api/health')" || exit 1

# ── Entry point ───────────────────────────────────────────────────────────────
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "5000", \
     "--workers", "1", "--log-level", "info"]
