"""
app/crud.py
─────────────────────────────────────────────────────────────────────────────
Database CRUD operations — the only module that issues SQL statements.

DESIGN PRINCIPLE
────────────────
All SQL is written here.  Routers call these functions; they never issue
SQL directly.  This separates business logic from persistence logic and
makes it easy to swap SQLite for PostgreSQL later.

All functions receive an aiosqlite.Connection as first argument (dependency
injected from get_db() in database.py).  Callers are responsible for the
transaction lifecycle (committing after writes).

NAMING CONVENTION
─────────────────
  get_*    — SELECT (returns one row, list, or None)
  create_* — INSERT (returns inserted record as dict)
  update_* — UPDATE (returns updated record as dict, or raises 404)
  delete_* — DELETE (returns deleted id, or raises 404)
  save_*   — INSERT complex record with child rows (simulation runs)
  log_*    — INSERT-only audit/event records (weather readings)
"""
from __future__ import annotations

import json
from datetime import datetime, timezone


def _utcnow() -> str:
    """Return current UTC time as ISO-8601 string (timezone-aware)."""
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
from typing import Optional

import aiosqlite
from fastapi import HTTPException

from app.database import row_to_dict
from app.models import ApplianceCreate, ApplianceUpdate


# ─────────────────────────────────────────────────────────────────────────────
# ELECTRICAL DERIVATION HELPER
# ─────────────────────────────────────────────────────────────────────────────

def _derive_watts(v: float, a: float, pf: float, eff: float) -> tuple[float, float]:
    """
    Compute derived electrical fields.

    Formula:
        watts           = voltage_V × current_A × power_factor
        effective_watts = watts / (efficiency_pct / 100)

    Returns: (watts, effective_watts) — both rounded to 2 decimal places.
    """
    w  = round(v * a * pf, 2)
    ew = round(w / max(eff / 100.0, 0.01), 2)
    return w, ew


# ─────────────────────────────────────────────────────────────────────────────
# APPLIANCE CRUD
# ─────────────────────────────────────────────────────────────────────────────

async def get_appliances(db: aiosqlite.Connection) -> list[dict]:
    """
    Fetch all appliances ordered by category priority then name.
    Returns a list of dicts suitable for the simulation engine.
    """
    cur = await db.execute(
        """SELECT * FROM appliances
           ORDER BY CASE cat WHEN 'high' THEN 0 WHEN 'medium' THEN 1 ELSE 2 END, name"""
    )
    rows = await cur.fetchall()
    return [row_to_dict(r) for r in rows]


async def get_appliance_by_id(db: aiosqlite.Connection, aid: int) -> Optional[dict]:
    """Fetch a single appliance by primary key. Returns None if not found."""
    cur = await db.execute("SELECT * FROM appliances WHERE id = ?", (aid,))
    row = await cur.fetchone()
    return row_to_dict(row) if row else None


async def create_appliance(db: aiosqlite.Connection, data: ApplianceCreate) -> dict:
    """
    Insert a new appliance.
    Derives watts and effective_watts from the electrical parameters.
    Returns the complete persisted record including auto-generated id.
    """
    w, ew = _derive_watts(data.voltage_v, data.current_a, data.power_factor, data.efficiency_pct)
    now = _utcnow()

    cur = await db.execute(
        """INSERT INTO appliances
           (name, cat, voltage_v, current_a, power_factor, efficiency_pct,
            duty_cycle_pct, hrs, watts, effective_watts, on_state,
            sched, icon, clr, is_custom, created_at, updated_at)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,1,?,?)""",
        (data.name, data.cat, data.voltage_v, data.current_a, data.power_factor,
         data.efficiency_pct, data.duty_cycle_pct, data.hrs, w, ew,
         int(data.on), data.sched, data.icon, data.clr, now, now),
    )
    await db.commit()
    return await get_appliance_by_id(db, cur.lastrowid)


async def update_appliance(db: aiosqlite.Connection, aid: int, data: ApplianceUpdate) -> dict:
    """
    Partial update (PATCH semantics) — only provided fields are written.
    Recomputes watts/effective_watts if any electrical field changes.
    Raises HTTP 404 if the appliance does not exist.
    """
    existing = await get_appliance_by_id(db, aid)
    if existing is None:
        raise HTTPException(status_code=404, detail=f"Appliance {aid} not found")

    # Merge: start from existing, overwrite with incoming non-None fields
    updated = {**existing}
    for field, value in data.model_dump(exclude_none=True).items():
        updated[field] = value

    # Recompute derived fields
    w, ew = _derive_watts(
        updated["voltage_v"], updated["current_a"],
        updated["power_factor"], updated["efficiency_pct"],
    )

    now = _utcnow()
    await db.execute(
        """UPDATE appliances
           SET name=?, cat=?, voltage_v=?, current_a=?, power_factor=?,
               efficiency_pct=?, duty_cycle_pct=?, hrs=?, watts=?,
               effective_watts=?, on_state=?, sched=?, icon=?, clr=?, updated_at=?
           WHERE id=?""",
        (updated["name"], updated["cat"], updated["voltage_v"], updated["current_a"],
         updated["power_factor"], updated["efficiency_pct"], updated["duty_cycle_pct"],
         updated["hrs"], w, ew, int(updated.get("on", True)),
         updated["sched"], updated["icon"], updated["clr"], now, aid),
    )
    await db.commit()
    return await get_appliance_by_id(db, aid)


async def delete_appliance(db: aiosqlite.Connection, aid: int) -> int:
    """
    Delete an appliance by id.
    Returns the deleted id.
    Raises HTTP 404 if the appliance does not exist.
    NOTE: appliance_snapshots use a soft reference (nullable FK) so
    historical simulation records are not affected.
    """
    existing = await get_appliance_by_id(db, aid)
    if existing is None:
        raise HTTPException(status_code=404, detail=f"Appliance {aid} not found")
    await db.execute("DELETE FROM appliances WHERE id=?", (aid,))
    await db.commit()
    return aid


async def toggle_appliance(db: aiosqlite.Connection, aid: int, on: Optional[bool]) -> dict:
    """
    Toggle or explicitly set the on/off state of an appliance.
    If `on` is None, flips the current state.
    Returns the updated record.
    """
    existing = await get_appliance_by_id(db, aid)
    if existing is None:
        raise HTTPException(status_code=404, detail=f"Appliance {aid} not found")
    new_state = (not existing["on"]) if on is None else on
    await db.execute(
        "UPDATE appliances SET on_state=?, updated_at=? WHERE id=?",
        (int(new_state), _utcnow(), aid),
    )
    await db.commit()
    return {"id": aid, "on": new_state}


# ─────────────────────────────────────────────────────────────────────────────
# SIMULATION PERSISTENCE
# ─────────────────────────────────────────────────────────────────────────────

async def save_simulation_run(db: aiosqlite.Connection, result: dict, cfg: dict) -> int:
    """
    Persist a completed simulation run to the database.

    Writes three tables in one transaction:
      1. simulation_runs       — one header row with inputs + aggregates
      2. simulation_hourly     — 24 hourly data points for chart replay
      3. appliance_snapshots   — contribution of each active appliance

    Returns the new simulation_runs.id.

    This enables:
      - Historical comparison ("how did yesterday compare to today?")
      - Chart replay without re-running the simulation
      - Fleet analytics across multiple RVs
    """
    pillars = result.get("si_pillars", {})

    cur = await db.execute(
        """INSERT INTO simulation_runs (
             scenario, weather, occupants, experience, temperature_c,
             irradiance_factor, solar_output_kwh, battery_capacity_kwh,
             starting_soc, load_factor,
             si_score, si_grade, si_label, si_color,
             p1_autonomy, p2_solar, p3_safety, p4_reserve,
             total_load_kwh, total_sol_kwh, bat_draw_kwh,
             days_off_grid, peak_load_kw, min_soc, min_soc_h,
             soc_pct, soc_kwh, sol_coverage_pct, bat_temp_factor,
             sol_now, ld_now, net_now, duration_ms
           ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (
            result.get("scenario", cfg.get("scenario", "expected")),
            result.get("weather",  cfg.get("weather",  "sunny")),
            result.get("occupants", cfg.get("occupants", 2)),
            result.get("experience", cfg.get("experience", "normal")),
            result.get("temperature_c", cfg.get("temperature_c", 22.0)),
            cfg.get("irradiance_factor", 1.0),
            cfg.get("solar_output_kwh", 2.0),
            result.get("bat_cap", 45.0),
            cfg.get("starting_soc", 0.87),
            cfg.get("load_factor", 1.0),
            result.get("si_score"),
            result.get("si_grade"),
            result.get("si_label"),
            result.get("si_color"),
            pillars.get("p1"),
            pillars.get("p2"),
            pillars.get("p3"),
            pillars.get("p4"),
            result.get("total_load_kwh"),
            result.get("total_sol_kwh"),
            result.get("bat_draw_kwh"),
            result.get("days_off_grid"),
            result.get("peak_load_kw"),
            result.get("min_soc"),
            result.get("min_soc_h"),
            result.get("soc_pct"),
            result.get("soc_kwh"),
            result.get("sol_coverage_pct"),
            result.get("bat_temp_factor"),
            result.get("sol_now"),
            result.get("ld_now"),
            result.get("net_now"),
            result.get("ms"),
        ),
    )
    run_id = cur.lastrowid

    # Hourly breakdown (24 rows)
    sol_h  = result.get("sol_hourly", [0.0] * 24)
    ld_h   = result.get("load_hourly", [0.0] * 24)
    soc_h  = result.get("soc_hourly", [0.0] * 24)
    net_h  = result.get("net_hourly", [0.0] * 24)
    await db.executemany(
        "INSERT INTO simulation_hourly (run_id, hour, solar_kw, load_kw, soc_pct, net_kw) VALUES (?,?,?,?,?,?)",
        [(run_id, h, sol_h[h], ld_h[h], soc_h[h], net_h[h]) for h in range(24)],
    )

    # Appliance snapshots
    for a in result.get("breakdown", []):
        await db.execute(
            """INSERT INTO appliance_snapshots
               (run_id, appliance_db_id, name, cat, icon, clr,
                effective_watts, daily_kwh, share_pct, is_critical)
               VALUES (?,?,?,?,?,?,?,?,?,?)""",
            (run_id, a.get("id"), a["name"], a["cat"], a.get("icon", "🔌"),
             a.get("clr", "#0A84FF"), a.get("effective_watts", 0),
             a.get("daily_kwh", 0), a.get("share_pct", 0),
             int(a.get("is_critical", False))),
        )

    await db.commit()
    return run_id


async def get_simulation_history(db: aiosqlite.Connection, limit: int = 20) -> list[dict]:
    """
    Fetch the most recent simulation runs (header only, no hourly detail).
    Used by the docs / history view.
    """
    cur = await db.execute(
        "SELECT * FROM simulation_runs ORDER BY created_at DESC LIMIT ?", (limit,)
    )
    rows = await cur.fetchall()
    return [dict(r) for r in rows]


# ─────────────────────────────────────────────────────────────────────────────
# WEATHER LOG
# ─────────────────────────────────────────────────────────────────────────────

async def log_weather(db: aiosqlite.Connection, data: dict) -> None:
    """
    Insert one weather reading row.
    Called by POST /api/weather when the frontend sends Open-Meteo data.
    Non-fatal on failure — weather logging is best-effort.
    """
    try:
        await db.execute(
            """INSERT INTO weather_readings
               (lat, lon, city, temp_c, cloud_pct, wind_kmh,
                weather_code, irr_factor, wx_label, wx_icon)
               VALUES (?,?,?,?,?,?,?,?,?,?)""",
            (data.get("lat"), data.get("lon"), data.get("city"),
             data.get("temp_c"), data.get("cloud_pct"), data.get("wind_kmh"),
             data.get("weather_code"), data.get("irr_factor"),
             data.get("wx_label"), data.get("wx_icon")),
        )
        await db.commit()
    except Exception:
        pass  # Weather log is advisory — never fail the main request
