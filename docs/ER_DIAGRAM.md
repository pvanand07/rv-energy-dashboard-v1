# Entity-Relationship Diagram

## RV Energy Intelligence — Database Schema

Rendered with [Mermaid](https://mermaid.js.org/) — view in GitHub, VS Code, or mermaid.live

```mermaid
erDiagram

    %% ──────────────────────────────────────────────────────────────────────
    %% APPLIANCES
    %% The persistent library of electrical devices in the RV.
    %% Each row represents one physical appliance.
    %% ──────────────────────────────────────────────────────────────────────
    appliances {
        INTEGER id               PK  "Auto-increment primary key"
        TEXT    name             NN  "Human-readable label"
        TEXT    cat              NN  "high | medium | low"
        REAL    voltage_v        NN  "Supply voltage (V)"
        REAL    current_a        NN  "Rated current draw (A)"
        REAL    power_factor     NN  "cos φ — 0.1 to 1.0"
        REAL    efficiency_pct   NN  "Device + inverter efficiency %"
        REAL    duty_cycle_pct   NN  "On-time fraction of active window %"
        REAL    hrs              NN  "Daily active hours"
        REAL    watts            NN  "Derived: V × A × PF"
        REAL    effective_watts  NN  "Derived: watts / (eff/100)"
        INTEGER on_state         NN  "0 = disabled, 1 = enabled"
        TEXT    sched            NN  "Schedule type (24h|cycle|meal|...)"
        TEXT    icon             NN  "Emoji icon for UI"
        TEXT    clr              NN  "Hex colour for UI"
        INTEGER is_custom        NN  "0 = default, 1 = user-created"
        TEXT    created_at       NN  "ISO-8601 UTC timestamp"
        TEXT    updated_at       NN  "ISO-8601 UTC timestamp"
    }

    %% ──────────────────────────────────────────────────────────────────────
    %% SIMULATION_RUNS
    %% Every call to POST /api/simulate creates one row.
    %% Stores both the input configuration and the computed results.
    %% ──────────────────────────────────────────────────────────────────────
    simulation_runs {
        INTEGER id                   PK  "Auto-increment primary key"
        TEXT    created_at           NN  "ISO-8601 UTC timestamp"
        TEXT    scenario             NN  "expected | best | worst"
        TEXT    weather              NN  "sunny | partly | overcast | rainy"
        INTEGER occupants            NN  "Number of RV occupants"
        TEXT    experience           NN  "expert | normal | new"
        REAL    temperature_c        NN  "Ambient temperature °C"
        REAL    irradiance_factor    NN  "Cloud-cover correction (0–1)"
        REAL    solar_output_kwh     NN  "Target panel daily output (kWh)"
        REAL    battery_capacity_kwh NN  "Nominal pack size (kWh)"
        REAL    starting_soc         NN  "Initial SOC 0.0–1.0"
        REAL    load_factor          NN  "What-if load multiplier"
        REAL    si_score             "Stability Score 0.0–10.0"
        TEXT    si_grade             "S | A | B | C | D | F"
        TEXT    si_label             "Exceptional | … | Critical"
        TEXT    si_color             "Hex colour for grade"
        REAL    p1_autonomy          "Pillar 1: Energy Autonomy (0–3.5)"
        REAL    p2_solar             "Pillar 2: Solar Coverage (0–3.0)"
        REAL    p3_safety            "Pillar 3: Peak Safety (0–2.0)"
        REAL    p4_reserve           "Pillar 4: Reserve Floor (0–1.5)"
        REAL    total_load_kwh       "Total daily energy consumed"
        REAL    total_sol_kwh        "Total daily solar generated"
        REAL    bat_draw_kwh         "Net battery draw (load − solar)"
        REAL    days_off_grid        "Estimated days of autonomy"
        REAL    peak_load_kw         "Highest instantaneous load (kW)"
        REAL    min_soc              "Lowest SOC % seen during simulation"
        INTEGER min_soc_h            "Hour (0–23) when min SOC occurred"
        INTEGER soc_pct              "Starting SOC as percentage"
        REAL    soc_kwh              "Starting SOC in kWh"
        REAL    sol_coverage_pct     "Solar % of total load"
        REAL    bat_temp_factor      "LiFePO4 temperature derating factor"
        REAL    sol_now              "Solar kW at current hour"
        REAL    ld_now               "Load kW at current hour"
        REAL    net_now              "Net kW at current hour (sol − load)"
        REAL    duration_ms          "Simulation engine wall time (ms)"
    }

    %% ──────────────────────────────────────────────────────────────────────
    %% SIMULATION_HOURLY
    %% 24 rows per simulation run — one per hour.
    %% Enables chart replay without re-running the engine.
    %% ──────────────────────────────────────────────────────────────────────
    simulation_hourly {
        INTEGER id        PK  "Auto-increment primary key"
        INTEGER run_id    FK  "→ simulation_runs.id (CASCADE DELETE)"
        INTEGER hour      NN  "0–23 (UTC local hour)"
        REAL    solar_kw  NN  "Average solar generation this hour (kW)"
        REAL    load_kw   NN  "Average total load this hour (kW)"
        REAL    soc_pct   NN  "Battery SOC at start of this hour (%)"
        REAL    net_kw    NN  "Net power this hour: solar_kw − load_kw"
    }

    %% ──────────────────────────────────────────────────────────────────────
    %% APPLIANCE_SNAPSHOTS
    %% Records which appliances were active at time of each simulation
    %% and their energy contribution. appliance_db_id is a soft reference
    %% (nullable) so deleting an appliance doesn't orphan history.
    %% ──────────────────────────────────────────────────────────────────────
    appliance_snapshots {
        INTEGER id              PK  "Auto-increment primary key"
        INTEGER run_id          FK  "→ simulation_runs.id (CASCADE DELETE)"
        INTEGER appliance_db_id     "Soft ref → appliances.id (nullable)"
        TEXT    name            NN  "Appliance name at time of simulation"
        TEXT    cat             NN  "Category at time of simulation"
        TEXT    icon            NN  "Icon emoji"
        TEXT    clr             NN  "Hex colour"
        REAL    effective_watts NN  "Battery draw (W) at time of simulation"
        REAL    daily_kwh       NN  "Energy consumed this day (kWh)"
        REAL    share_pct       NN  "% of total daily load"
        INTEGER is_critical     NN  "1 if effective_watts > 1500"
    }

    %% ──────────────────────────────────────────────────────────────────────
    %% WEATHER_READINGS
    %% Audit log of all weather fetches from Open-Meteo.
    %% Standalone table — no FK to simulation_runs (readings may arrive
    %% between simulations).
    %% ──────────────────────────────────────────────────────────────────────
    weather_readings {
        INTEGER id           PK  "Auto-increment primary key"
        TEXT    recorded_at  NN  "ISO-8601 UTC timestamp"
        REAL    lat              "Latitude of the RV"
        REAL    lon              "Longitude of the RV"
        TEXT    city             "Reverse-geocoded city name"
        REAL    temp_c           "Temperature (°C)"
        REAL    cloud_pct        "Cloud cover (%)"
        REAL    wind_kmh         "Wind speed (km/h)"
        INTEGER weather_code     "WMO weather interpretation code"
        REAL    irr_factor       "Derived: 1 − (cloud/100)×0.92 + 0.05"
        TEXT    wx_label         "Human label (Clear, Overcast, etc.)"
        TEXT    wx_icon          "Emoji icon for condition"
    }

    %% ──────────────────────────────────────────────────────────────────────
    %% RELATIONSHIPS
    %% ──────────────────────────────────────────────────────────────────────
    simulation_runs      ||--o{ simulation_hourly    : "has 24 hourly rows"
    simulation_runs      ||--o{ appliance_snapshots  : "captures appliance state"
    appliances           |o--o{ appliance_snapshots  : "soft ref (nullable)"
```

---

## Relationship Explanations

### `simulation_runs` → `simulation_hourly` (one-to-many, CASCADE DELETE)
Each simulation run generates exactly 24 hourly rows (hours 0–23).
These enable chart replay in the UI without re-executing the 2880-step engine.
Deleting a simulation run cascades to delete all its hourly rows.

### `simulation_runs` → `appliance_snapshots` (one-to-many, CASCADE DELETE)
Each run captures the state of all active appliances at that point in time.
This creates a historical record independent of future appliance edits.
The `appliance_db_id` column is a **soft reference** (nullable FK) —
if the user later deletes an appliance, the historical snapshots survive.

### `appliances` → `appliance_snapshots` (zero-or-many, soft reference)
The `appliance_db_id` in `appliance_snapshots` is intentionally **not** a
hard foreign key constraint. This allows deleting appliances without
invalidating historical simulation records.

---

## Index Strategy

```sql
-- Appliances: fast filter by category and on-state (used in every simulation)
CREATE INDEX idx_appliances_cat ON appliances(cat);
CREATE INDEX idx_appliances_on  ON appliances(on_state);

-- Simulation runs: reverse-chronological listing
CREATE INDEX idx_sim_runs_created ON simulation_runs(created_at DESC);

-- Hourly data: fast JOIN from run header to hourly detail
CREATE INDEX idx_sim_hourly_run ON simulation_hourly(run_id);

-- Snapshots: fast JOIN from run header to appliance detail
CREATE INDEX idx_snap_run ON appliance_snapshots(run_id);
```

---

## Scale Path

| Scale tier | Storage | Notes |
|---|---|---|
| Single RV, local | SQLite (current) | Zero config, file portable |
| Multi-RV fleet, shared | PostgreSQL + TimescaleDB | Concurrent writes, time-series hypertables for hourly data |
| IoT telemetry (30-second live) | InfluxDB or TimescaleDB | Columnar compression for high-frequency data |

The application's async design (`aiosqlite` → `asyncpg`) makes migration
straightforward — only `database.py` and `crud.py` need to change.
