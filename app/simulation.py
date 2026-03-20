"""
app/simulation.py
─────────────────────────────────────────────────────────────────────────────
Core RV energy simulation engine — 2880-step (30-second resolution).

ARCHITECTURE
────────────
This module is intentionally a pure-function module with no I/O.
It receives all configuration as a dict, runs the simulation, and returns
a result dict.  FastAPI routers call this module; the module never touches
the database or HTTP layer.

SIMULATION LOOP
───────────────
The engine iterates over 2880 time steps (one every 30 seconds = 1 full day).
At each step it:
  1. Computes solar power generated (kW) from the irradiance curve
  2. Computes total appliance load (kW) by summing all active appliances,
     each weighted by their schedule duty factor and duty cycle %
  3. Updates battery state-of-charge by integrating the net power over DT_H
  4. Records the solar, load, and SOC values for post-processing

After the loop:
  - Collapses 2880 steps → 24 hourly averages for chart rendering
  - Computes aggregate energy statistics (total_solar, total_load, etc.)
  - Calls stability.compute_stability_score() for the composite score
  - Generates alerts and optimisation tips based on results

KEY PHYSICS
───────────
  Solar power per step:
    solar_kW(step) = daily_target_kWh × irradiance_shape(h) / integral
    where integral = Σ irradiance_shape(s × DT_H) × DT_H  (energy normaliser)

  Appliance power per step:
    load_kW(step) = Σ (effective_W / 1000) × duty(sched, step) × (dc / 100)
                        × experience_factor × load_scenario_factor

  Battery state update:
    kwh_new = clamp(kwh_old + (solar_kW − load_kW) × DT_H, 0, max_kwh)

  LiFePO4 temperature derating:
    <  0°C → ×0.70  (30% capacity loss — severe cold)
    < 10°C → ×0.85  (15% capacity loss — cold)
    < 20°C → ×0.95  (5% capacity loss  — cool)
    ≥ 20°C → ×1.00  (no loss           — nominal)
    max_kwh = capacity × 0.95 × temp_factor
    (0.95 = LiFePO4 usable fraction, protecting top and bottom ~2.5%)

  Electrical power chain per appliance:
    apparent_VA    = voltage_V × current_A
    real_W         = apparent_VA × power_factor
    effective_W    = real_W / (efficiency_pct / 100)   ← battery draw
    daily_kWh      = (effective_W / 1000) × (duty_cycle / 100) × hrs

SCHEDULE TYPES
──────────────
  24h     → constant 1.0 (routers, Starlink, cameras)
  cycle   → compressor cycling: 3.5× for 22/90 steps, 0.06 standby
  meal    → 1.0 at 07:15, 12:30, 18:30 (8-min windows) — stove/microwave
  burst   → 1.0 for 10 steps (~5 min) every 150 min — water heater
  morning → 0.6 from 06:00–09:00 — coffee machine
  evening → 0.92 from 18:00–23:00 — TV, music
  lights  → 0.9 evening / 0.08 daytime — LED lights
  day     → 0.70 × occupancy_factor (10:00–20:00); 0.08 idle — AC
  once    → 1.0 single block starting 03:00; duration = hrs × 120 steps
"""
from __future__ import annotations

import math
import time as _time

from app.config import (
    STEPS, DT_H,
    WEATHER_FACTOR, EXPERIENCE_FACTOR,
    SCENARIO_LOAD_FACTOR, SCENARIO_SOLAR_FACTOR,
)
from app.stability import compute_stability_score


# ─────────────────────────────────────────────────────────────────────────────
# SOLAR IRRADIANCE MODEL
# ─────────────────────────────────────────────────────────────────────────────

def solar_curve(h: float) -> float:
    """
    Normalised solar irradiance shape at hour h.

    Uses a sine arch between 06:00 and 20:00 (14-hour solar window):
        f(h) = sin(π × (h − 6) / 14)   for 6 ≤ h ≤ 20
        f(h) = 0                         otherwise

    Peak occurs at h = 13:00 (solar noon midpoint between 6 and 20).

    The simulation divides the target daily kWh by the integral of this curve
    (precomputed once per run) so the area under the step curve exactly equals
    the target — regardless of step resolution.

    Physical accuracy: For mid-latitudes (25°N–55°N) where most North American
    RVs travel, this approximation is within 5–10% of actual pyranometer data
    for clear-sky conditions. Open-Meteo cloud_cover adjusts the result for
    actual sky conditions.
    """
    if h < 6.0 or h > 20.0:
        return 0.0
    return math.sin(((h - 6.0) / 14.0) * math.pi)


# ─────────────────────────────────────────────────────────────────────────────
# APPLIANCE LOAD SCHEDULE
# ─────────────────────────────────────────────────────────────────────────────

def app_duty(sched: str, step: int, hrs: float, users: int) -> float:
    """
    Load schedule duty multiplier (0.0 – 3.5) at simulation step `step`.

    The multiplier is multiplied into:
        (effective_watts / 1000) × duty_multiplier × (duty_cycle / 100)
    to get instantaneous power at each step.

    Values > 1.0 are only used for the 'cycle' schedule to model the
    brief high-draw phase of a compressor startup.

    Parameters
    ──────────
    sched  : Schedule type name (one of the 9 types defined below)
    step   : Integer step index 0 – 2879
    hrs    : Appliance daily active hours (used for 'once' schedule duration)
    users  : Number of occupants (used in 'day' occupancy scaling)

    Schedule definitions:
    ─────────────────────
    24h     Always 1.0 — constant background loads (router, camera, Starlink)

    cycle   Models a refrigerator compressor cycling:
              step % 90 < 22  → 3.5× (compressor on, high draw + startup spike)
              else            → 0.06 (fan only, standby draw)
            Period = 90 steps = 45 minutes; ON phase = 22 steps ≈ 24%

    meal    Burst at three mealtime windows (breakfast, lunch, dinner):
              07:15–07:23  → 1.0
              12:30–12:38  → 1.0
              18:30–18:38  → 1.0
              else         → 0.0

    burst   Short periodic pulse (water heater maintaining tank temp):
              step % 300 < 10 → 1.0 (5 minutes every 2.5 hours)
              else            → 0.0

    morning Coffee machine and morning routine appliances:
              06:00–09:00 → 0.6 (not full power — intermittent use)
              else        → 0.0

    evening Entertainment and evening appliances:
              18:00–23:00 → 0.92
              else        → 0.0

    lights  LED lights — high evening, low pilot light daytime:
              18:00–23:00 → 0.9
              else        → 0.08  (night light / indicator LEDs)

    day     Air conditioning — scales with number of occupants:
              10:00–20:00 → 0.70 × occupancy_factor  (active period)
              else        → 0.08  (idle / overnight purge)
              occupancy_factor = 0.7 + (users / 12) × 0.3
                2 occupants → 0.75×   4 → 0.80×   8 → 0.90×

    once    Single contiguous run starting at 03:00 local:
              step 360 to (360 + hrs × 120) → 1.0
              else                          → 0.0
            Used for: washer (0.75h), dryer (0.75h), air fryer (0.33h)
            Duration in steps = hrs × (3600 / 30) = hrs × 120
    """
    h = step * DT_H
    u = 0.7 + (users / 12) * 0.3  # occupancy scaling factor

    if sched == "24h":     return 1.0
    if sched == "cycle":   return 3.5 if step % 90 < 22 else 0.06
    if sched == "meal":
        for mt in (7.25, 12.5, 18.5):
            if mt <= h < mt + 0.14:
                return 1.0
        return 0.0
    if sched == "burst":   return 1.0 if step % 300 < 10 else 0.0
    if sched == "morning": return 0.60 if 6  <= h < 9  else 0.0
    if sched == "evening": return 0.92 if 18 <= h < 23 else 0.0
    if sched == "lights":  return 0.90 if 18 <= h < 23 else 0.08
    if sched == "day":     return 0.70 * u if 10 <= h < 20 else 0.08
    if sched == "once":
        s0 = 360
        return 1.0 if s0 <= step < s0 + int(hrs * 120) else 0.0
    # Fallback for unknown schedules: distribute hrs evenly across the day
    return hrs / 24.0


# ─────────────────────────────────────────────────────────────────────────────
# MAIN SIMULATION FUNCTION
# ─────────────────────────────────────────────────────────────────────────────

def run_simulation(cfg: dict) -> dict:
    """
    Execute a full 24-hour energy simulation.

    Parameters (cfg dict keys)
    ──────────────────────────
    appliances           : list[dict]  Active appliance records from database
    battery_capacity_kwh : float       Nominal battery capacity
    starting_soc         : float       Initial state-of-charge (0.0 – 1.0)
    solar_output_kwh     : float       Panel daily output at full sun (kWh)
    weather              : str         Weather condition key
    scenario             : str         Load scenario key
    occupants            : int         Number of occupants
    experience           : str         User experience level key
    load_factor          : float       Additional load multiplier (from what-if slider)
    temperature_c        : float       Ambient temperature for LiFePO4 derating
    irradiance_factor    : float       Real-time cloud-cover correction (from Open-Meteo)

    Returns
    ───────
    dict matching SimulateResponse schema (see app/models.py)
    """
    t0 = _time.monotonic()

    # ── Unpack config ──────────────────────────────────────────────────────
    apps      = cfg.get("appliances", [])
    bat_cap   = float(cfg.get("battery_capacity_kwh", 45.0))
    start_soc = float(cfg.get("starting_soc", 0.87))
    sol_out   = float(cfg.get("solar_output_kwh", 2.0))
    weather   = cfg.get("weather",   "sunny")
    scenario  = cfg.get("scenario",  "expected")
    users     = int(  cfg.get("occupants",  2))
    exp       = cfg.get("experience","normal")
    load_fac  = float(cfg.get("load_factor", 1.0))
    temp_c    = float(cfg.get("temperature_c", 22.0))
    irr_fac   = float(cfg.get("irradiance_factor", 1.0))

    # ── Scale factors ──────────────────────────────────────────────────────
    wx_int  = WEATHER_FACTOR.get(weather, 1.0)
    em      = EXPERIENCE_FACTOR.get(exp, 1.0)
    sl_fac  = SCENARIO_SOLAR_FACTOR.get(scenario, 1.0)
    ld_fac  = SCENARIO_LOAD_FACTOR.get(scenario, 1.0) * load_fac

    # ── LiFePO4 temperature derating ──────────────────────────────────────
    if   temp_c < 0:   bat_temp_f = 0.70
    elif temp_c < 10:  bat_temp_f = 0.85
    elif temp_c < 20:  bat_temp_f = 0.95
    else:              bat_temp_f = 1.00

    max_kwh = bat_cap * 0.95 * bat_temp_f   # 0.95 = LiFePO4 usable fraction
    kwh     = min(start_soc * bat_cap * 0.95, max_kwh)

    # ── Solar normalisation ────────────────────────────────────────────────
    # Precompute the integral of the irradiance curve so the target kWh is
    # distributed proportionally across daylight hours.
    cs      = sum(solar_curve(s * DT_H) for s in range(STEPS)) * DT_H
    sol_tgt = sol_out * wx_int * sl_fac * irr_fac

    # ── Main simulation loop (2880 steps × 30 seconds = 24 hours) ─────────
    solar_arr: list[float] = []
    load_arr:  list[float] = []
    soc_arr:   list[float] = []

    # Per-appliance energy accumulator (index → kWh) — used for accurate breakdown
    app_kwh: list[float] = [0.0] * len(apps)

    kwh_start = kwh  # snapshot initial charge for autonomy + soc_kwh reporting

    for s in range(STEPS):
        h  = s * DT_H

        # Solar power this step
        sk = (sol_tgt * solar_curve(h) / cs) if cs > 0 else 0.0

        # Total appliance load this step
        lk = 0.0
        for i, a in enumerate(apps):
            if not a.get("on", True):
                continue
            ew   = float(a.get("effective_watts", a.get("watts", 0)))
            dc   = float(a.get("duty_cycle_pct", 100)) / 100.0
            duty = app_duty(a.get("sched", "24h"), s, a.get("hrs", 1), users)
            step_kw = (ew / 1000.0) * duty * dc * em * ld_fac
            lk += step_kw
            app_kwh[i] += step_kw * DT_H  # accumulate per-appliance energy (kWh)

        # Battery state update (energy balance integration)
        kwh = max(0.0, min(max_kwh, kwh + (sk - lk) * DT_H))

        solar_arr.append(round(sk, 4))
        load_arr.append( round(lk, 4))
        soc_arr.append(  round(kwh / max_kwh * 100.0, 2) if max_kwh > 0 else 0.0)

    # ── Collapse to 24 hourly buckets ──────────────────────────────────────
    # Each hourly value = mean of 120 consecutive steps (60 min / 30 s = 120)
    def h24(arr: list[float]) -> list[float]:
        return [round(sum(arr[h * 120:(h + 1) * 120]) / 120.0, 3) for h in range(24)]

    sol_h = h24(solar_arr)
    ld_h  = h24(load_arr)
    soc_h = [soc_arr[h * 120] for h in range(24)]
    net_h = [round(sol_h[h] - ld_h[h], 3) for h in range(24)]

    # ── Aggregate statistics ───────────────────────────────────────────────
    tl   = sum(load_arr)  * DT_H   # total load kWh
    ts   = sum(solar_arr) * DT_H   # total solar kWh
    bd   = max(0.0, tl - ts)       # net battery draw kWh (deficit)
    cov  = min(1.0, ts / tl) if tl > 0 else 1.0   # solar coverage ratio

    # Days off-grid = initial usable energy / daily net draw
    # Use kwh_start (already temperature-derated and clamped to max_kwh) — not a
    # re-derived formula — to avoid double-applying bat_temp_f.
    days = (kwh_start / bd) if bd > 0.01 else 999.0
    pk   = max(load_arr)                    # peak instantaneous kW
    mn   = min(soc_arr)                     # minimum SOC % seen
    mnh  = next((h for h in range(24) if soc_h[h] == min(soc_h)), 0)

    # ── Stability Score ────────────────────────────────────────────────────
    score, grade, label, si_color, pillars = compute_stability_score(cov, days, pk, mn)

    # ── Current-hour snapshot (real-time display) ──────────────────────────
    import time as _t
    nh  = _t.localtime().tm_hour
    sn  = sol_h[nh]
    ln  = ld_h[nh]
    nn  = round(sn - ln, 3)

    # ── Per-appliance energy breakdown ────────────────────────────────────
    # daily_kwh is taken from app_kwh[] — accumulated in the simulation loop —
    # so it exactly matches the energy each appliance contributed to tl.
    breakdown: list[dict] = []
    for i, a in enumerate(apps):
        if not a.get("on", True):
            continue
        ew = float(a.get("effective_watts", a.get("watts", 0)))
        dk = round(app_kwh[i], 3)  # index matches enumerate() in simulation loop
        breakdown.append({
            "id":             a.get("id", 0),
            "name":           a["name"],
            "icon":           a.get("icon", "🔌"),
            "cat":            a["cat"],
            "clr":            a.get("clr", "#5E9EFF"),
            "watts":          a.get("watts", 0),
            "effective_watts": ew,
            "voltage_v":      a.get("voltage_v", 0),
            "current_a":      a.get("current_a", 0),
            "power_factor":   a.get("power_factor", 1),
            "efficiency_pct": a.get("efficiency_pct", 100),
            "duty_cycle_pct": a.get("duty_cycle_pct", 100),
            "hrs":            a.get("hrs", 1),
            "daily_kwh":      dk,
            "share_pct":      round(dk / tl * 100, 1) if tl > 0 else 0.0,
            "is_critical":    ew > 1000,   # aligned with surge-alert threshold
        })
    breakdown.sort(key=lambda x: x["daily_kwh"], reverse=True)

    # ── Alerts ────────────────────────────────────────────────────────────
    sp     = round(start_soc * 100)
    alerts: list[dict] = []

    if sp < 20:
        alerts.append({"sev": "critical", "msg": "Battery critically low — connect shore power immediately"})
    elif sp < 35:
        alerts.append({"sev": "warning",  "msg": f"Battery at {sp}% — estimated {days:.1f} days remaining"})

    if days < 1:
        alerts.append({"sev": "critical", "msg": "Battery will deplete within 24 hours at current load"})
    elif days < 2:
        alerts.append({"sev": "warning",  "msg": f"Low range — approx {round(days * 24)}h off-grid autonomy"})

    hi_loads = [a for a in apps if a.get("on") and a.get("effective_watts", 0) > 1000]
    if len(hi_loads) >= 3:
        alerts.append({"sev": "warning", "msg": f"{len(hi_loads)} high-power loads simultaneous — surge risk"})

    if temp_c < 5:
        alerts.append({"sev": "warning", "msg": f"Temperature {temp_c:.0f}°C — LiFePO4 capacity reduced"})

    if score < 5.0:
        alerts.append({"sev": "critical", "msg": f"Stability Score {score}/10 (Grade F) — immediate action required"})
    elif score < 7.0:
        alerts.append({"sev": "warning",  "msg": f"Stability Score {score}/10 (Grade {grade}) — review energy balance"})

    if weather == "rainy":
        alerts.append({"sev": "info", "msg": "Rainy conditions — solar minimal, battery is primary source"})

    if not alerts:
        alerts.append({"sev": "info", "msg": "All systems nominal — energy balance healthy"})

    # ── Optimisation tips ─────────────────────────────────────────────────
    tips: list[dict] = []
    dryer = next((a for a in apps if a.get("on") and "dryer" in a.get("name", "").lower()), None)
    ac    = next((a for a in apps if a.get("on") and "air conditioner" in a.get("name", "").lower()), None)

    if dryer:
        tips.append({"gain": "+1.8d",     "msg": "Disable dryer — single largest daily drain"})
    if ac:
        tips.append({"gain": "+2.1d",     "msg": "Reduce AC duty cycle to 50% — major autonomy gain"})
    tips.append(    {"gain": "+0.4 kWh",  "msg": "Schedule high-draw loads 10am–2pm (peak solar)"})
    if users > 2:
        tips.append({"gain": f"+{round((users-2)*0.3,1)} kWh/d", "msg": "Fewer occupants reduces AC load (occupancy scaling on day schedule)"})
    if temp_c < 10:
        tips.append({"gain": "+8% cap",  "msg": "Insulate battery bay — recover cold-derating loss"})
    if cov < 0.5:
        tips.append({"gain": "+3.0 pts SI", "msg": "Double solar panel capacity to reach Grade A stability"})

    # ── Assemble result ───────────────────────────────────────────────────
    dd, dh_val = int(days), round((days - int(days)) * 24)

    return {
        "soc_pct":          sp,
        "soc_kwh":          round(kwh_start, 1),
        "bat_cap":          bat_cap,
        "bat_temp_factor":  round(bat_temp_f, 2),
        "tte":              "No depletion projected" if days > 99 else f"{dd}d {dh_val}h remaining",
        "tte_ok":           days > 3,
        "sol_now":          sn,
        "ld_now":           ln,
        "net_now":          nn,
        # Stability Score
        "si_score":         score,
        "si_grade":         grade,
        "si_label":         label,
        "si_color":         si_color,
        "si_pillars":       pillars,
        # Energy summary
        "days_off_grid":    round(min(days, 999), 1),
        "total_load_kwh":   round(tl, 2),
        "total_sol_kwh":    round(ts, 2),
        "bat_draw_kwh":     round(bd, 2),
        "min_soc":          round(mn, 1),
        "min_soc_h":        mnh,
        "peak_load_kw":     round(pk, 3),
        "sol_coverage_pct": round(cov * 100, 1),
        # Chart data
        "sol_hourly":       sol_h,
        "load_hourly":      ld_h,
        "soc_hourly":       soc_h,
        "net_hourly":       net_h,
        # Detail
        "breakdown":        breakdown,
        "alerts":           alerts,
        "tips":             tips,
        # Echo config
        "scenario":         scenario,
        "weather":          weather,
        "occupants":        users,
        "experience":       exp,
        "temperature_c":    temp_c,
        # Perf
        "ms":               round((_time.monotonic() - t0) * 1000, 1),
    }
