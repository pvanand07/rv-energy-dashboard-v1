"""
app/routers/simulate.py
─────────────────────────────────────────────────────────────────────────────
FastAPI router — simulation and weather endpoints.

ENDPOINT SUMMARY
────────────────
  POST /api/simulate   → run full 2880-step simulation, persist result
  POST /api/weather    → log a live weather reading from the frontend
  GET  /api/history    → recent simulation run history (last 20)

SIMULATION FLOW
───────────────
  1. Validate SimulateRequest (Pydantic)
  2. Load active appliances from SQLite
  3. Call simulation.run_simulation(cfg)   — pure function, no I/O
  4. Persist run to DB via crud.save_simulation_run (async)
  5. Return SimulateResponse to client

Persistence is fire-and-forget from the client's perspective — the HTTP
response is sent with the simulation result regardless of whether the DB
write succeeds.  DB errors are logged but do not fail the request.
"""
from __future__ import annotations

import logging

from fastapi import APIRouter

from app.database import get_db
from app.models import SimulateRequest, SimulateResponse, WeatherReading
from app import crud
from app.simulation import run_simulation

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["Simulation"])


@router.post("/simulate", response_model=SimulateResponse, summary="Run energy simulation")
async def simulate(req: SimulateRequest):
    """
    Execute a full 24-hour energy simulation and return results.

    The simulation engine (app/simulation.py) runs 2880 steps at 30-second
    resolution, tracking solar generation, appliance load, and battery SOC
    at every step.  Results are aggregated into 24 hourly buckets for charts.

    After the simulation, results are persisted to simulation_runs,
    simulation_hourly, and appliance_snapshots tables for historical analysis.

    The `solar_intensity` field (0.0 – 1.0) is a what-if slider multiplier
    applied on top of solar_output_kwh — useful for exploring scenarios.
    """
    async with get_db() as db:
        appliances = await crud.get_appliances(db)

    # Build config dict (mirrors the old Flask/in-memory pattern)
    cfg: dict = req.model_dump()
    cfg["appliances"] = appliances

    # Apply what-if solar intensity multiplier if provided
    if req.solar_intensity is not None:
        cfg["solar_output_kwh"] = cfg["solar_output_kwh"] * req.solar_intensity

    # Run the simulation (pure function — no async needed inside)
    result = run_simulation(cfg)

    # Persist asynchronously — don't fail request if DB write fails
    try:
        async with get_db() as db:
            await crud.save_simulation_run(db, result, cfg)
    except Exception as exc:
        logger.warning("Failed to persist simulation run: %s", exc)

    return result


@router.post("/weather", summary="Log live weather reading")
async def log_weather(reading: WeatherReading):
    """
    Store a weather reading received from the frontend after Open-Meteo fetch.
    Used for: audit trail, historical weather correlation, future ML features.
    """
    async with get_db() as db:
        await crud.log_weather(db, reading.model_dump())
    return {"logged": True}


@router.get("/history", summary="Simulation run history")
async def history(limit: int = 20):
    """
    Return the most recent simulation runs (header only, no hourly data).
    Used by the documentation / history view.
    """
    async with get_db() as db:
        runs = await crud.get_simulation_history(db, limit)
    return runs
