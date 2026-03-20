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

import httpx
from fastapi import APIRouter, HTTPException, Query

from app.database import get_db
from app.models import SimulateRequest, SimulateResponse, WeatherReading, WeatherResponse
from app import crud
from app.simulation import run_simulation

# WMO weather code → (category, icon, label)
_WMO: dict[int, tuple[str, str, str]] = {
    0:  ("sunny",    "☀️", "Clear"),
    1:  ("sunny",    "🌤", "Mainly clear"),
    2:  ("partly",   "⛅", "Partly cloudy"),
    3:  ("overcast", "☁️", "Overcast"),
    45: ("overcast", "🌫", "Foggy"),
    51: ("rainy",    "🌦", "Drizzle"),
    61: ("rainy",    "🌧", "Light rain"),
    63: ("rainy",    "🌧", "Moderate rain"),
    80: ("rainy",    "🌦", "Showers"),
    95: ("rainy",    "⛈", "Thunderstorm"),
}

def _wmo(code: int) -> tuple[str, str, str]:
    return _WMO.get(code) or _WMO.get((code // 10) * 10) or ("sunny", "🌤", "Mixed")

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


@router.get("/weather", response_model=WeatherResponse, summary="Fetch live weather from Open-Meteo")
async def get_weather(
    lat: float = Query(..., description="Latitude"),
    lon: float = Query(..., description="Longitude"),
):
    """
    Backend proxy for Open-Meteo.  Fetches current conditions for the given
    coordinates, maps the WMO weather code to a simulation category, computes
    the irradiance factor from cloud cover, logs the reading, and returns the
    processed result.
    """
    url = (
        f"https://api.open-meteo.com/v1/forecast"
        f"?latitude={lat:.4f}&longitude={lon:.4f}"
        f"&current=temperature_2m,weather_code,cloud_cover,wind_speed_10m"
        f"&timezone=auto&forecast_days=1"
    )
    try:
        async with httpx.AsyncClient(timeout=8.0) as client:
            resp = await client.get(url)
            resp.raise_for_status()
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=502, detail=f"Open-Meteo unavailable: {exc}") from exc

    cur = resp.json()["current"]
    wx, icon, lbl = _wmo(int(cur["weather_code"]))
    irr_factor = round(max(0.05, min(1.05, 1 - (cur["cloud_cover"] / 100) * 0.92 + 0.05)), 2)

    # Reverse-geocode city name via Nominatim
    city = "Unknown"
    try:
        async with httpx.AsyncClient(timeout=5.0, headers={"Accept-Language": "en"}) as client:
            geo = await client.get(
                f"https://nominatim.openstreetmap.org/reverse"
                f"?lat={lat}&lon={lon}&format=json&zoom=10",
                headers={"User-Agent": "rv-energy-intelligence/1.0"},
            )
            if geo.is_success:
                addr = geo.json().get("address", {})
                city = (addr.get("city") or addr.get("town") or addr.get("village")
                        or addr.get("county") or "Unknown").split(",")[0]
    except Exception:
        pass

    payload = {
        "lat": lat, "lon": lon,
        "city":         city,
        "temp_c":       round(cur["temperature_2m"]),
        "cloud_pct":    cur["cloud_cover"],
        "wind_kmh":     round(cur["wind_speed_10m"]),
        "weather_code": int(cur["weather_code"]),
        "irr_factor":   irr_factor,
        "wx_label":     lbl,
        "wx_icon":      icon,
    }
    try:
        async with get_db() as db:
            await crud.log_weather(db, payload)
    except Exception as exc:
        logger.warning("Weather log failed: %s", exc)

    return WeatherResponse(
        temp_c=payload["temp_c"],
        cloud_pct=payload["cloud_pct"],
        wind_kmh=payload["wind_kmh"],
        weather_code=payload["weather_code"],
        wx=wx,
        icon=icon,
        lbl=lbl,
        irr_factor=irr_factor,
        city=city,
    )


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
