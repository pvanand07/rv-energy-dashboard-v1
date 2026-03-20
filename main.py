"""
main.py
─────────────────────────────────────────────────────────────────────────────
RV Energy Intelligence v2.1 — FastAPI Application Entry Point
Elevatics AI | Apple Design Edition

ARCHITECTURE
────────────
  main.py            ← you are here — app factory + lifespan
  app/
    config.py        ← environment settings & constants
    database.py      ← SQLite init, connection manager, seeding
    models.py        ← Pydantic request/response schemas
    simulation.py    ← 2880-step energy simulation engine
    stability.py     ← Stability Score (0-10) computation
    crud.py          ← all SQL operations (no SQL in routers)
    routers/
      pages.py       ← GET /  (serves Jinja2 HTML template)
      appliances.py  ← /api/appliances  CRUD
      simulate.py    ← /api/simulate + /api/weather + /api/history
      health.py      ← /api/health

STARTUP SEQUENCE (lifespan)
────────────────────────────
  1. Call init_db() — creates SQLite tables if they don't exist
  2. Seeds 19 default appliances if the appliances table is empty
  3. Registers all routers
  4. Serves requests

RUN
───
  Development (auto-reload):
    uvicorn main:app --reload --port 5000

  Production (multi-worker):
    uvicorn main:app --host 0.0.0.0 --port 5000 --workers 4

  Or use the __main__ guard below:
    python main.py
"""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.config import HOST, PORT, DEBUG, APP_TITLE, APP_VERSION, APP_TAGLINE
from app.database import init_db
from app.routers.pages       import router_pages
from app.routers.appliances  import router as router_appliances
from app.routers.simulate    import router as router_simulate
from app.routers.health      import router as router_health
from app.routers.test        import router as router_test

# ─────────────────────────────────────────────────────────────────────────────
# LOGGING
# ─────────────────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.WARNING,
    format="%(asctime)s  %(levelname)-8s  %(name)s  %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("rv_energy")
logger.setLevel(logging.DEBUG if DEBUG else logging.INFO)


# ─────────────────────────────────────────────────────────────────────────────
# LIFESPAN (startup / shutdown)
# ─────────────────────────────────────────────────────────────────────────────
@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    FastAPI lifespan context manager.

    STARTUP:
      • Initialises SQLite schema (idempotent — safe on every restart)
      • Seeds 19 default appliances if appliances table is empty
      • Logs service info

    SHUTDOWN:
      • No explicit teardown needed; aiosqlite closes connections per-request
    """
    logger.info("═" * 58)
    logger.info("  %s  v%s", APP_TITLE, APP_VERSION)
    logger.info("  %s", APP_TAGLINE)
    logger.info("═" * 58)
    logger.info("Initialising database…")
    await init_db()
    logger.info("Database ready. Serving at http://%s:%d", HOST, PORT)
    logger.info("API docs → http://%s:%d/docs", HOST, PORT)
    logger.info("═" * 58)
    yield
    logger.info("Shutdown complete.")


# ─────────────────────────────────────────────────────────────────────────────
# APP FACTORY
# ─────────────────────────────────────────────────────────────────────────────
app = FastAPI(
    title=APP_TITLE,
    version=APP_VERSION,
    description=f"""
{APP_TAGLINE}

## RV Energy Intelligence

A production-grade energy management and prediction system for recreational vehicles.

### Key Features
- **Stability Score 0-10** — composite index across 4 pillars (Autonomy, Solar, Safety, Reserve)
- **Real-time weather** — live irradiance from Open-Meteo API (no key required)
- **LiFePO4 battery model** — temperature derating at 4 bands
- **2880-step simulation** — 30-second resolution for sub-minute surge detection
- **Full appliance CRUD** — complete electrical model per device (V, A, PF, eff%, duty%)
- **SQLite persistence** — all runs, hourly charts, and appliance snapshots stored

### API Reference
All endpoints are documented below. The interactive UI at `/` provides
the full Apple-design dashboard experience.
    """,
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url="/redoc",
)


# ─────────────────────────────────────────────────────────────────────────────
# MIDDLEWARE
# ─────────────────────────────────────────────────────────────────────────────
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],          # Tighten in production to specific origins
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ─────────────────────────────────────────────────────────────────────────────
# STATIC FILES
# ─────────────────────────────────────────────────────────────────────────────
app.mount("/static", StaticFiles(directory="static"), name="static")


# ─────────────────────────────────────────────────────────────────────────────
# ROUTERS
# ─────────────────────────────────────────────────────────────────────────────
app.include_router(router_pages)       # GET /  (HTML)
app.include_router(router_appliances)  # /api/appliances
app.include_router(router_simulate)    # /api/simulate + /api/weather + /api/history
app.include_router(router_health)      # /api/health
app.include_router(router_test)        # /api/test


# ─────────────────────────────────────────────────────────────────────────────
# ENTRY POINT
# ─────────────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    uvicorn.run(
        "main:app",
        host="localhost",
        port=8001,
        reload=True,
        log_level="debug",
    )
