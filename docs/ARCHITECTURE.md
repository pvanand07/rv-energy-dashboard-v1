# System Architecture

## RV Energy Intelligence v2.1 — Elevatics AI

---

## Overview

```
Browser / RV HMI Tablet
        │
        │ HTTP (JSON + HTML)
        ▼
┌─────────────────────────────────────────────────────────────────┐
│                        FastAPI Application                       │
│                          (main.py)                              │
│                                                                 │
│  Middleware: CORS, Static Files                                  │
│                                                                 │
│  Routers                                                        │
│  ├── pages.py        GET /              → HTML (Jinja2)         │
│  ├── appliances.py   /api/appliances    → CRUD endpoints        │
│  ├── simulate.py     /api/simulate      → Simulation endpoint   │
│  │                   /api/weather       → Weather log           │
│  │                   /api/history       → Run history           │
│  └── health.py       /api/health        → Health check          │
│                                                                 │
│  Core Modules                                                   │
│  ├── simulation.py   2880-step engine (pure function)           │
│  ├── stability.py    Stability Score computation                │
│  ├── crud.py         All SQL operations                         │
│  ├── database.py     SQLite init + connection manager           │
│  ├── models.py       Pydantic schemas                           │
│  └── config.py       Settings + constants                       │
└─────────────────────────────────────────────────────────────────┘
        │
        │ aiosqlite (async)
        ▼
┌─────────────────────────────────────────────────────────────────┐
│                     SQLite Database                              │
│                  ./data/rv_energy.db                            │
│                                                                 │
│  Tables                                                         │
│  ├── appliances            (19 default + user-created)          │
│  ├── simulation_runs       (one row per /api/simulate call)     │
│  ├── simulation_hourly     (24 rows per run — chart data)       │
│  ├── appliance_snapshots   (appliance state at run time)        │
│  └── weather_readings      (Open-Meteo fetch log)               │
└─────────────────────────────────────────────────────────────────┘
```

---

## Request Lifecycle — POST /api/simulate

```
Client (browser)
    │
    │ POST /api/simulate
    │ { battery_capacity_kwh, starting_soc, solar_output_kwh,
    │   weather, scenario, occupants, experience,
    │   temperature_c, irradiance_factor, load_factor }
    │
    ▼
FastAPI (simulate.py router)
    │
    ├─► Pydantic validation (SimulateRequest)
    │        • Type coercion (str → float, etc.)
    │        • Range checks (soc 0.05–1.0, occupants 1–12, …)
    │        • HTTP 422 with error detail on failure
    │
    ├─► Load appliances from SQLite
    │        async with get_db() as db:
    │            appliances = await crud.get_appliances(db)
    │        Returns list[dict] ordered by category then name
    │
    ├─► Apply solar_intensity multiplier (if what-if slider used)
    │
    ├─► simulation.run_simulation(cfg)
    │        │
    │        ├─ Scale factors (weather, experience, scenario, load)
    │        ├─ LiFePO4 temperature derating (4 bands)
    │        ├─ Solar normalisation integral (ensures target kWh accuracy)
    │        │
    │        ├─ 2880-step loop (30 s × 2880 = 24 h):
    │        │    for step in range(2880):
    │        │        solar_kW = sol_tgt × irradiance_curve(h) / integral
    │        │        load_kW  = Σ (eff_W/1000) × schedule(step) × duty_cycle
    │        │        kwh      = clamp(kwh + (solar−load) × DT_H, 0, max_kwh)
    │        │
    │        ├─ Collapse → 24 hourly averages (chart data)
    │        ├─ Compute aggregates (total_load, total_sol, days, peak, min_soc)
    │        ├─ stability.compute_stability_score(cov, days, peak, min_soc)
    │        └─ Build alerts + tips → return result dict
    │
    ├─► crud.save_simulation_run(db, result, cfg)
    │        │
    │        ├─ INSERT simulation_runs (1 row)
    │        ├─ INSERT simulation_hourly (24 rows)
    │        └─ INSERT appliance_snapshots (N rows, one per active appliance)
    │
    └─► Return SimulateResponse (Pydantic-validated JSON)
            → 24-hour chart data, stability score, alerts, tips, breakdown
```

---

## Module Dependency Graph

```
main.py
├── app/config.py          (no internal deps — reads os.environ)
├── app/database.py        (→ config)
├── app/models.py          (no internal deps — pure Pydantic)
├── app/stability.py       (no internal deps — pure math)
├── app/simulation.py      (→ config, stability)
├── app/crud.py            (→ database, models)
└── app/routers/
    ├── pages.py           (→ database, crud, simulation, config)
    ├── appliances.py      (→ database, models, crud)
    ├── simulate.py        (→ database, models, crud, simulation)
    └── health.py          (→ database, config, models)
```

**Key design principle:** `simulation.py` and `stability.py` are **pure functions** — they receive configuration dicts, perform computation, and return result dicts. They never touch the database, make HTTP calls, or use async. This makes them:
- Independently testable (no database setup needed)
- Reusable from any context (CLI, tests, background tasks)
- Easy to parallelise (no shared state)

---

## Simulation Engine — Deep Dive

### Time Resolution

```
1 day = 86,400 seconds
Step size = 30 seconds
Steps per day = 86,400 / 30 = 2,880

DT_H = 30 / 3600 = 0.008333... hours per step
```

30-second resolution catches events invisible to hourly models:
- Microwave 5-minute burst at mealtime
- Water heater 5-minute maintenance cycle
- Refrigerator compressor startup spike (3.5× rated current)

### Solar Model

```python
# Irradiance shape (sine arch over 14-hour solar window)
def solar_curve(h: float) -> float:
    if h < 6 or h > 20: return 0.0
    return sin(π × (h - 6) / 14)

# Normalisation (ensures daily target is exactly met)
integral = Σ solar_curve(step × DT_H) × DT_H  [for step in 0..2879]

# Per-step power (kW)
solar_kW(step) = daily_target_kWh × solar_curve(h) / integral
```

The normalisation integral (≈ 4.46 h for a 14-h window) divides out so that
`Σ solar_kW(step) × DT_H = daily_target_kWh` exactly, regardless of step count.

Real-time correction:
```
daily_target = panel_kWh × weather_factor × irr_factor × scenario_factor
irr_factor   = 1 - (cloud_cover% / 100) × 0.92 + 0.05
```

### Battery Model (LiFePO4)

```
Temperature bands:
  temp < 0°C   → × 0.70  (30% loss — severe cold)
  temp < 10°C  → × 0.85  (15% loss — cold)
  temp < 20°C  → × 0.95  ( 5% loss — cool)
  temp ≥ 20°C  → × 1.00  (no loss  — nominal)

Usable capacity:
  max_kWh = nominal_kWh × 0.95 × temp_factor
  (0.95 = LiFePO4 safe operating range, protecting cells at both ends)

Step update:
  kwh_new = clamp(kwh + (solar_kW − load_kW) × DT_H, 0, max_kWh)
```

---

## Stability Score — Computation Detail

```
Input variables:
  sol_cov  = min(1.0, total_solar_kWh / total_load_kWh)
  days     = (starting_kWh) / max(net_draw_kWh, 0.01)
  peak_kw  = max(load_arr)   [peak instantaneous load]
  min_soc  = min(soc_arr)    [lowest SOC % in 24h]

Pillar formulas:
  P1 = min(3.5, (days / 14) × 3.5)
  P2 = min(3.0, sol_cov × 3.0)
  P3 = min(2.0, max(0, (1 − peak_kw / 5.0)) × 2.0)
  P4 = min(1.5, max(0, (min_soc − 20) / 80) × 1.5)

Total:
  SI = P1 + P2 + P3 + P4   →   range: 0.0 – 10.0

Grade thresholds:
  SI ≥ 9.0  → S  Exceptional   (#30D158)
  SI ≥ 8.0  → A  Excellent     (#34C759)
  SI ≥ 7.0  → B  Good          (#5AC8F5)
  SI ≥ 6.0  → C  Fair          (#0A84FF)
  SI ≥ 5.0  → D  Poor          (#FF9F0A)
  SI <  5.0  → F  Critical      (#FF453A)
```

---

## Database Design Decisions

### Why SQLite?

| Consideration | SQLite | PostgreSQL |
|---|---|---|
| Configuration | Zero (file) | Server setup required |
| Concurrency | WAL = concurrent reads | Native concurrent writes |
| Deployment | Copy one file | Docker + volume |
| RV use case | Single device, periodic writes | Multi-device fleet |
| Migration path | `asyncpg` swap in crud.py | Ready to go |

For a single RV on a Jetson AGX Orin, SQLite with WAL mode is ideal.

### WAL Mode

```sql
PRAGMA journal_mode = WAL;
```

WAL (Write-Ahead Logging) allows:
- Multiple concurrent readers during a write
- Faster writes (append to WAL file, not in-place)
- Crash-safe — WAL is replayed on restart

### Cascade Delete

`simulation_hourly` and `appliance_snapshots` both have:
```sql
REFERENCES simulation_runs(id) ON DELETE CASCADE
```

Deleting a simulation run removes all 24+ associated rows automatically.

### Soft Reference

`appliance_snapshots.appliance_db_id` is **nullable** (no FK constraint).
This means deleting an appliance never orphans historical simulation data.

---

## Frontend Architecture

The UI is a **server-rendered Jinja2 template** (`templates/index.html`) with vanilla JavaScript.

### Data Flow

```
1. Server renders index.html with initial simulation data:
   <script>const IDAT = {{ d|tojson }};</script>

2. JavaScript uses IDAT to populate dashboard on first load
   (no extra HTTP round-trip for initial render)

3. User interactions trigger fetch() calls to /api/simulate
   → Response updates DOM in-place (no page reload)

4. Weather: browser requests GPS → fetch Open-Meteo
   → POST /api/weather (log to DB)
   → callSim() with new weather params
```

### No Build Step

The frontend uses:
- Chart.js 4.4 via CDN (cdnjs.cloudflare.com)
- Apple system fonts (`-apple-system, BlinkMacSystemFont, "SF Pro"`)
- CSS variables for theming
- Vanilla JS `fetch()` for API calls

No webpack, Vite, npm, or React needed. The whole frontend is one HTML file
that works offline (after first load) and deploys as a single artifact.

---

## Scale Path

### Phase 1 — Current (Single RV, SQLite)
```
Jetson AGX Orin → FastAPI → SQLite
Capacity: 1 RV, ~100 simulations/day, ~50 appliances
```

### Phase 2 — Small Fleet (Multi-RV, PostgreSQL)
```
Replace: aiosqlite → asyncpg
Change: database.py connection strings + crud.py SQL syntax
Add: TimescaleDB hypertable for simulation_hourly (time-series)
Capacity: 10–100 RVs, concurrent simulations
```

### Phase 3 — Large Fleet (Microservices)
```
Extract simulation engine → separate FastAPI microservice
Add MQTT broker (HiveMQ/EMQX) for live BMS telemetry
Add InfluxDB for 30-second SOC time series
Add Grafana for fleet dashboards
Capacity: 1000+ RVs
```

---

## Security Notes

- CORS is permissive (`allow_origins=["*"]`) — tighten to your domain in production
- No authentication (RV is a single-user device) — add OAuth2 for fleet deployments
- SQLite path is configurable via `DB_PATH` env — use an absolute path in production
- Debug mode (`DEBUG=false`) hides stack traces from API responses
