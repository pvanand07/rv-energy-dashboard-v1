"""
app/database.py
─────────────────────────────────────────────────────────────────────────────
Async SQLite database layer using aiosqlite.

DESIGN DECISIONS
────────────────
• aiosqlite wraps stdlib sqlite3 in a thread pool so coroutines never block.
• WAL (Write-Ahead Logging) mode allows concurrent readers during writes —
  critical when the simulation endpoint is running while the UI polls.
• Foreign key enforcement is ON per connection; SQLite disables it by default.
• Row factory is set to sqlite3.Row so columns are accessible by name.
• A single DB file lives in ./data/rv_energy.db (configured via DB_PATH env).

SCHEMA OVERVIEW
───────────────
  appliances          — persistent appliance library (survives restart)
  simulation_runs     — every simulation execution with all inputs + outputs
  simulation_hourly   — 24 hourly data points per simulation run (for charts)
  appliance_snapshots — appliance state captured at time of each simulation
  weather_readings    — live weather data received from Open-Meteo

SEEDING
───────
  If the appliances table is empty on startup, 19 default appliances are
  inserted (the same defaults previously held in memory). This makes the
  app functional immediately without any configuration.
"""
from __future__ import annotations

import json
import math
import sqlite3
from contextlib import asynccontextmanager
from typing import AsyncGenerator

import aiosqlite

from app.config import DB_PATH

# ─────────────────────────────────────────────────────────────────────────────
# DDL — table definitions
# ─────────────────────────────────────────────────────────────────────────────
_DDL = """
PRAGMA journal_mode = WAL;
PRAGMA foreign_keys = ON;
PRAGMA cache_size    = -32768;   -- 32 MB page cache

-- ── Appliance library ──────────────────────────────────────────────────────
-- Stores the persistent appliance definitions that the user manages via UI.
-- Each row represents one physical device in the RV.
CREATE TABLE IF NOT EXISTS appliances (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    name           TEXT    NOT NULL,
    cat            TEXT    NOT NULL DEFAULT 'medium'
                           CHECK (cat IN ('high', 'medium', 'low')),
    -- Electrical parameters (see app/simulation.py for usage)
    voltage_v      REAL    NOT NULL DEFAULT 120.0,
    current_a      REAL    NOT NULL DEFAULT 1.0,
    power_factor   REAL    NOT NULL DEFAULT 0.95
                           CHECK (power_factor BETWEEN 0.1 AND 1.0),
    efficiency_pct REAL    NOT NULL DEFAULT 90.0
                           CHECK (efficiency_pct BETWEEN 1 AND 100),
    duty_cycle_pct REAL    NOT NULL DEFAULT 100.0
                           CHECK (duty_cycle_pct BETWEEN 1 AND 100),
    hrs            REAL    NOT NULL DEFAULT 4.0
                           CHECK (hrs BETWEEN 0 AND 24),
    -- Derived (recomputed on every save, stored for fast reads)
    watts          REAL    NOT NULL DEFAULT 114.0,
    effective_watts REAL   NOT NULL DEFAULT 126.67,
    -- State
    on_state       INTEGER NOT NULL DEFAULT 1
                           CHECK (on_state IN (0, 1)),
    sched          TEXT    NOT NULL DEFAULT '24h',
    icon           TEXT    NOT NULL DEFAULT '🔌',
    clr            TEXT    NOT NULL DEFAULT '#0A84FF',
    is_custom      INTEGER NOT NULL DEFAULT 0
                           CHECK (is_custom IN (0, 1)),
    created_at     TEXT    NOT NULL DEFAULT (datetime('now')),
    updated_at     TEXT    NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_appliances_cat ON appliances(cat);
CREATE INDEX IF NOT EXISTS idx_appliances_on  ON appliances(on_state);

-- ── Simulation runs ────────────────────────────────────────────────────────
-- Every call to POST /api/simulate creates one row here.
-- Inputs capture what the user configured; results capture computed outputs.
-- This enables historical comparison ("how did last Tuesday's config differ?")
CREATE TABLE IF NOT EXISTS simulation_runs (
    id                   INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at           TEXT    NOT NULL DEFAULT (datetime('now')),
    -- ── Input configuration ─────────────────────────────────────────────
    scenario             TEXT    NOT NULL DEFAULT 'expected',
    weather              TEXT    NOT NULL DEFAULT 'sunny',
    occupants            INTEGER NOT NULL DEFAULT 2,
    experience           TEXT    NOT NULL DEFAULT 'normal',
    temperature_c        REAL    NOT NULL DEFAULT 22.0,
    irradiance_factor    REAL    NOT NULL DEFAULT 1.0,
    solar_output_kwh     REAL    NOT NULL DEFAULT 2.0,
    battery_capacity_kwh REAL    NOT NULL DEFAULT 45.0,
    starting_soc         REAL    NOT NULL DEFAULT 0.87,
    load_factor          REAL    NOT NULL DEFAULT 1.0,
    -- ── Stability Index pillars (0-10 total) ────────────────────────────
    si_score             REAL,   -- 0.0 – 10.0 composite score
    si_grade             TEXT,   -- S / A / B / C / D / F
    si_label             TEXT,   -- Exceptional / Excellent / ... / Critical
    si_color             TEXT,   -- Hex colour for gauge rendering
    p1_autonomy          REAL,   -- Pillar 1: 0 – 3.5
    p2_solar             REAL,   -- Pillar 2: 0 – 3.0
    p3_safety            REAL,   -- Pillar 3: 0 – 2.0
    p4_reserve           REAL,   -- Pillar 4: 0 – 1.5
    -- ── Energy results ──────────────────────────────────────────────────
    total_load_kwh       REAL,
    total_sol_kwh        REAL,
    bat_draw_kwh         REAL,
    days_off_grid        REAL,
    peak_load_kw         REAL,
    min_soc              REAL,
    min_soc_h            INTEGER,
    soc_pct              INTEGER,
    soc_kwh              REAL,
    sol_coverage_pct     REAL,
    bat_temp_factor      REAL,
    -- ── Real-time snapshot (current hour) ───────────────────────────────
    sol_now              REAL,
    ld_now               REAL,
    net_now              REAL,
    duration_ms          REAL
);

CREATE INDEX IF NOT EXISTS idx_sim_runs_created ON simulation_runs(created_at DESC);

-- ── Hourly breakdown per simulation run ───────────────────────────────────
-- 24 rows per simulation_run (one per hour).
-- Used to render charts without re-running the simulation.
CREATE TABLE IF NOT EXISTS simulation_hourly (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id    INTEGER NOT NULL REFERENCES simulation_runs(id) ON DELETE CASCADE,
    hour      INTEGER NOT NULL CHECK (hour BETWEEN 0 AND 23),
    solar_kw  REAL    NOT NULL DEFAULT 0.0,
    load_kw   REAL    NOT NULL DEFAULT 0.0,
    soc_pct   REAL    NOT NULL DEFAULT 0.0,
    net_kw    REAL    NOT NULL DEFAULT 0.0,
    UNIQUE (run_id, hour)
);

CREATE INDEX IF NOT EXISTS idx_sim_hourly_run ON simulation_hourly(run_id);

-- ── Appliance snapshot at time of simulation ──────────────────────────────
-- Records which appliances were active and their contribution.
-- appliance_db_id may be NULL if the appliance was deleted after the run.
CREATE TABLE IF NOT EXISTS appliance_snapshots (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id          INTEGER NOT NULL REFERENCES simulation_runs(id) ON DELETE CASCADE,
    appliance_db_id INTEGER,          -- FK to appliances.id (nullable — soft ref)
    name            TEXT    NOT NULL,
    cat             TEXT    NOT NULL,
    icon            TEXT    NOT NULL DEFAULT '🔌',
    clr             TEXT    NOT NULL DEFAULT '#0A84FF',
    effective_watts REAL    NOT NULL DEFAULT 0.0,
    daily_kwh       REAL    NOT NULL DEFAULT 0.0,
    share_pct       REAL    NOT NULL DEFAULT 0.0,
    is_critical     INTEGER NOT NULL DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_snap_run ON appliance_snapshots(run_id);

-- ── Live weather readings ─────────────────────────────────────────────────
-- Stores each weather fetch from Open-Meteo.
-- Used for: audit trail, offline analysis, future ML feature engineering.
CREATE TABLE IF NOT EXISTS weather_readings (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    recorded_at  TEXT    NOT NULL DEFAULT (datetime('now')),
    lat          REAL,
    lon          REAL,
    city         TEXT,
    temp_c       REAL,
    cloud_pct    REAL,
    wind_kmh     REAL,
    weather_code INTEGER,
    irr_factor   REAL,
    wx_label     TEXT,
    wx_icon      TEXT
);
"""

# ─────────────────────────────────────────────────────────────────────────────
# DEFAULT APPLIANCE SEED DATA
# ─────────────────────────────────────────────────────────────────────────────
def _default_appliances() -> list[dict]:
    """
    Returns 19 default appliances with full electrical parameters.
    Inserted once when the database is first initialised.

    Electrical derivation:
        watts          = voltage_v × current_a × power_factor
        effective_watts = watts / (efficiency_pct / 100)
    """
    rows = [
        #  name                    cat       V       A     PF   eff   dc   hrs    on     sched     icon  clr
        ("Electric stove",       "high",   240,  8.33, 1.00,  98, 100, 0.50, False, "meal",    "🔥","#FF6B6B"),
        ("Refrigerator",         "high",   120,  1.25, 0.95,  85,  25, 24.0, True,  "cycle",   "❄️","#5E9EFF"),
        ("Washer",               "high",   120,  7.08, 0.92,  90, 100, 0.75, False, "once",    "🫧","#BF5AF2"),
        ("Dryer",                "high",   240, 11.67, 1.00,  92, 100, 0.75, False, "once",    "💨","#FF9F0A"),
        ("Water heater (main)",  "high",   240, 12.50, 1.00,  97, 100, 0.75, True,  "burst",   "🚿","#FF6B6B"),
        ("Water heater (bath)",  "high",   240,  6.25, 1.00,  97, 100, 0.25, False, "burst",   "🛁","#FFD60A"),
        ("Air conditioner",      "high",   240,  9.17, 0.88,  85,  70, 6.00, False, "day",     "🌬️","#5AC8F5"),
        ("Microwave",           "medium",  120, 10.00, 0.96,  90, 100, 0.17, True,  "meal",    "📡","#FF9F0A"),
        ("Air fryer",           "medium",  120, 12.50, 0.98,  95, 100, 0.33, False, "once",    "🍟","#FF6B6B"),
        ("Coffee machine",      "medium",  120,  9.17, 0.97,  88, 100, 0.25, True,  "morning", "☕","#AC8E68"),
        ("Garbage disposer",    "medium",  120,  4.17, 0.90,  85, 100, 0.01, False, "burst",   "🗑","#636366"),
        ("TV",                   "low",    120,  1.00, 0.92,  82, 100, 4.00, True,  "evening", "📺","#5E9EFF"),
        ("Music system",         "low",    120,  0.63, 0.88,  80, 100, 3.00, True,  "evening", "🎵","#BF5AF2"),
        ("Starlink",             "low",     48,  1.25, 0.94,  88, 100, 24.0, True,  "24h",     "🛰️","#30D158"),
        ("WiFi router",          "low",     12,  1.25, 0.90,  85, 100, 24.0, True,  "24h",     "📶","#30D158"),
        ("Security cameras",     "low",     12,  2.50, 0.92,  90, 100, 24.0, True,  "24h",     "📷","#636366"),
        ("Tablet HMI",           "low",     12,  1.00, 0.91,  88, 100, 24.0, True,  "24h",     "📱","#5E9EFF"),
        ("LED lights",           "low",     12, 16.67, 0.95,  92,  90, 5.00, True,  "lights",  "💡","#FFD60A"),
        ("Fan(s)",               "low",    120,  0.63, 0.88,  82,  80, 20.0, True,  "24h",     "🌀","#5AC8F5"),
    ]
    out = []
    for r in rows:
        name, cat, v, a, pf, eff, dc, hrs, on, sched, icon, clr = r
        w   = round(v * a * pf, 1)
        ew  = round(w / (eff / 100), 1)
        out.append({
            "name": name, "cat": cat,
            "voltage_v": v, "current_a": a, "power_factor": pf,
            "efficiency_pct": eff, "duty_cycle_pct": dc, "hrs": hrs,
            "watts": w, "effective_watts": ew,
            "on_state": int(on), "sched": sched,
            "icon": icon, "clr": clr, "is_custom": 0,
        })
    return out


# ─────────────────────────────────────────────────────────────────────────────
# CONNECTION HELPERS
# ─────────────────────────────────────────────────────────────────────────────
@asynccontextmanager
async def get_db() -> AsyncGenerator[aiosqlite.Connection, None]:
    """
    Async context manager that opens a database connection, sets
    row_factory so columns are addressable by name, and closes on exit.

    Usage:
        async with get_db() as db:
            rows = await db.execute_fetchall("SELECT * FROM appliances")
    """
    async with aiosqlite.connect(DB_PATH) as conn:
        conn.row_factory = aiosqlite.Row
        await conn.execute("PRAGMA foreign_keys = ON")
        await conn.execute("PRAGMA journal_mode = WAL")
        yield conn


# ─────────────────────────────────────────────────────────────────────────────
# INITIALISATION
# ─────────────────────────────────────────────────────────────────────────────
async def init_db() -> None:
    """
    Create all tables (idempotent — safe to call on every startup).
    Seeds 19 default appliances if the table is empty.
    Called from the FastAPI lifespan context manager in main.py.

    Uses executescript() to run the full DDL atomically so every table
    is guaranteed to exist before any request is served.
    """
    async with aiosqlite.connect(DB_PATH) as conn:
        conn.row_factory = aiosqlite.Row
        # executescript issues an implicit COMMIT, handles multi-statement DDL,
        # and strips comments — the correct tool for schema initialisation.
        await conn._execute(conn._conn.executescript, _DDL)
        await conn.commit()

        # Seed defaults if empty
        cur = await conn.execute("SELECT COUNT(*) as n FROM appliances")
        row = await cur.fetchone()
        if row["n"] == 0:
            defaults = _default_appliances()
            await conn.executemany(
                """INSERT INTO appliances
                   (name, cat, voltage_v, current_a, power_factor, efficiency_pct,
                    duty_cycle_pct, hrs, watts, effective_watts, on_state,
                    sched, icon, clr, is_custom)
                   VALUES (:name, :cat, :voltage_v, :current_a, :power_factor,
                           :efficiency_pct, :duty_cycle_pct, :hrs, :watts,
                           :effective_watts, :on_state, :sched, :icon, :clr, :is_custom)""",
                defaults,
            )
            await conn.commit()


def row_to_dict(row: aiosqlite.Row) -> dict:
    """Convert an aiosqlite.Row to a plain dict, remapping on_state → on."""
    d = dict(row)
    if "on_state" in d:
        d["on"] = bool(d.pop("on_state"))
    if "is_custom" in d:
        d["is_custom"] = bool(d["is_custom"])
    return d
