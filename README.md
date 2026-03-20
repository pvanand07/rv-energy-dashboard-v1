# RV Energy Intelligence v2.1

**Elevatics AI** — Apple Design Edition  
*The gold standard for RV resource estimation and prediction.*

---

## Overview

A production-grade energy management system for recreational vehicles that combines:

- **2880-step simulation** at 30-second resolution (30 s × 2880 = 24 h)
- **Stability Score 0–10** — composite index across four weighted pillars
- **Live weather integration** — Open-Meteo API, no key required
- **LiFePO4 battery model** — temperature derating at four thermal bands
- **Full appliance CRUD** — complete electrical model per device
- **Apple HIG design** — system fonts, glass morphism, semantic colours
- **FastAPI backend** — async, typed, OpenAPI documented
- **SQLite persistence** — zero-config, portable, upgradeable

---

## Quick Start

```bash
# 1. Clone
git clone https://github.com/elevatics-ai/rv-energy-intelligence
cd rv-energy-intelligence

# 2. Install
pip install -r requirements.txt

# 3. Run
uvicorn main:app --reload --port 5000

# 4. Open
open http://localhost:5000
```

> **No configuration required.** The database is created automatically on first run
> and seeded with 19 default appliances.

---

## Project Structure

```
rv-energy-intelligence/
├── main.py                      # FastAPI app factory + lifespan + routers
├── requirements.txt
├── .gitignore
├── .env.example                 # Environment variable reference
│
├── app/
│   ├── config.py                # All settings + constants (env-overridable)
│   ├── database.py              # SQLite init, connection manager, seeding
│   ├── models.py                # Pydantic v2 request/response schemas
│   ├── simulation.py            # 2880-step simulation engine (pure function)
│   ├── stability.py             # Stability Score 0-10 computation
│   ├── crud.py                  # All SQL — CRUD + simulation persistence
│   └── routers/
│       ├── pages.py             # GET / → serves Jinja2 HTML template
│       ├── appliances.py        # /api/appliances CRUD (6 endpoints)
│       ├── simulate.py          # /api/simulate + /api/weather + /api/history
│       └── health.py            # /api/health (database connectivity check)
│
├── templates/
│   └── index.html               # Apple-design single-page app (Jinja2)
│
├── static/                      # CSS / JS assets (currently inlined in HTML)
│
├── data/
│   └── rv_energy.db             # SQLite database (created at runtime)
│
└── docs/
    ├── ER_DIAGRAM.md            # Mermaid entity-relationship diagram
    └── ARCHITECTURE.md          # System architecture reference
```

---

## API Reference

Interactive docs available at `http://localhost:5000/docs` (Swagger UI)
and `http://localhost:5000/redoc` (ReDoc).

### Appliances

| Method | Path | Description |
|--------|------|-------------|
| `GET`    | `/api/appliances`           | List all appliances |
| `POST`   | `/api/appliances`           | Create appliance |
| `GET`    | `/api/appliances/{id}`      | Get one appliance |
| `PUT`    | `/api/appliances/{id}`      | Update appliance (partial) |
| `DELETE` | `/api/appliances/{id}`      | Delete appliance |
| `POST`   | `/api/appliances/{id}/toggle` | Toggle on/off state |

### Simulation

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/api/simulate` | Run 24-hour simulation |
| `POST` | `/api/weather`  | Log weather reading from frontend |
| `GET`  | `/api/history`  | Recent simulation runs (last 20) |
| `GET`  | `/api/health`   | Service health check |

### Simulate Request Body

```json
{
  "battery_capacity_kwh": 45.0,
  "starting_soc": 0.87,
  "solar_output_kwh": 6.0,
  "weather": "sunny",
  "scenario": "expected",
  "occupants": 2,
  "experience": "normal",
  "load_factor": 1.0,
  "temperature_c": 22.0,
  "irradiance_factor": 0.85,
  "solar_intensity": 1.0
}
```

---

## Stability Score — 0 to 10

The single most important number. Higher = healthier.

| Pillar | Max pts | Formula | Question |
|--------|---------|---------|----------|
| P1 Energy Autonomy | 3.5 | `min(3.5, days/14 × 3.5)` | How many days can I survive? |
| P2 Solar Coverage | 3.0 | `min(3.0, solar/load × 3.0)` | Is the sun keeping up? |
| P3 Peak Safety | 2.0 | `min(2.0, (1 − peak/5.0) × 2.0)` | Will I trip my inverter? |
| P4 Reserve Floor | 1.5 | `min(1.5, (min_soc−20)/80 × 1.5)` | Does battery stay healthy? |

### Grade Scale

| Grade | Score | Label | Action |
|-------|-------|-------|--------|
| S | 9.0–10.0 | Exceptional | None — off-grid gold standard |
| A | 8.0–8.9 | Excellent | Minor optimisations available |
| B | 7.0–7.9 | Good | Schedule loads around peak solar |
| C | 6.0–6.9 | Fair | Monitor; shore up if rainy days ahead |
| D | 5.0–5.9 | Poor | Shed loads; plan for shore power |
| **F** | **0.0–4.9** | **Critical** | **Immediate action required** |

> **Grade F** means the system cannot sustain itself. At least one of:
> battery depletes in <2 days, solar covers <33% of load, peak exceeds
> inverter limit, or battery dips below the 20% LiFePO4 safety floor.

---

## Electrical Model

Every appliance stores six electrical parameters. The server derives
`watts` and `effective_watts` automatically:

```
apparent_VA   = voltage_V × current_A
real_W        = apparent_VA × power_factor
effective_W   = real_W / (efficiency_pct / 100)   ← battery draw
daily_kWh     = (effective_W / 1000) × (duty_cycle / 100) × hrs
```

---

## Database Schema

Five tables in SQLite:

| Table | Purpose |
|-------|---------|
| `appliances` | Persistent appliance library |
| `simulation_runs` | Every simulation with inputs + results |
| `simulation_hourly` | 24 hourly data points per run (chart replay) |
| `appliance_snapshots` | Appliance contribution at time of each run |
| `weather_readings` | Audit log of live weather fetches |

See [docs/ER_DIAGRAM.md](docs/ER_DIAGRAM.md) for the full entity-relationship diagram.

---

## Environment Variables

```bash
DB_PATH=/custom/path/rv_energy.db   # Default: ./data/rv_energy.db
HOST=0.0.0.0                        # Default: 0.0.0.0
PORT=5000                           # Default: 5000
DEBUG=false                         # Default: true
```

Copy `.env.example` to `.env` and adjust as needed.

---

## Development

```bash
# Install with dev dependencies
pip install -r requirements.txt

# Run with auto-reload
uvicorn main:app --reload --port 5000

# View API docs
open http://localhost:5000/docs

# Inspect database
sqlite3 data/rv_energy.db ".tables"
sqlite3 data/rv_energy.db "SELECT si_score, si_grade, created_at FROM simulation_runs ORDER BY created_at DESC LIMIT 5;"
```

---

## Production Deployment

```bash
# Multi-worker (CPU bound workloads)
uvicorn main:app --host 0.0.0.0 --port 8080 --workers 4

# Docker
docker build -t rv-energy .
docker run -p 5000:5000 -v $(pwd)/data:/app/data rv-energy
```

> For fleet deployments with multiple simultaneous RVs, replace SQLite
> with PostgreSQL + TimescaleDB. Only `database.py` and `crud.py` need
> to change — the simulation engine and routers are I/O-free.

---

## Technology Stack

| Layer | Technology | Why |
|-------|------------|-----|
| Web framework | FastAPI 0.111 | Async, typed, auto-OpenAPI |
| ASGI server | Uvicorn | Production-grade, low latency |
| Template engine | Jinja2 | Server-side render for SEO + fast FCP |
| Database driver | aiosqlite | Async SQLite, thread-pool backed |
| Data validation | Pydantic v2 | Request/response schemas + auto docs |
| Charts | Chart.js 4.4 | Lightweight, no build step |
| Design system | Apple HIG | System fonts, semantic colours, glass morphism |
| Weather API | Open-Meteo | Free, no API key, globally accurate |

---

## Licence

MIT © 2025 Elevatics AI

---

*Built by Elevatics AI — Connected Mobility Intelligence*
