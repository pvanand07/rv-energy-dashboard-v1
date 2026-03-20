"""
app/models.py
─────────────────────────────────────────────────────────────────────────────
Pydantic v2 schemas for all FastAPI request bodies and response payloads.

WHY PYDANTIC?
─────────────
• Automatic validation: invalid field types return HTTP 422 with clear errors
• Self-documenting: FastAPI generates OpenAPI schema from these models
• Type safety: IDE autocompletion throughout the codebase
• Coercion: strings like "120" are automatically cast to float where declared

NAMING CONVENTION
─────────────────
  XxxCreate  — body of POST requests (no `id`, no computed fields)
  XxxUpdate  — body of PUT requests (all fields optional)
  XxxRead    — response body (full record, includes `id` and computed fields)
  XxxRequest — body of action endpoints (simulate, toggle)
  XxxResponse — generic action response
"""
from __future__ import annotations

from typing import Any, Optional
from pydantic import BaseModel, Field, field_validator


# ─────────────────────────────────────────────────────────────────────────────
# APPLIANCE SCHEMAS
# ─────────────────────────────────────────────────────────────────────────────

class ApplianceCreate(BaseModel):
    """
    Body for POST /api/appliances.
    All electrical fields are required; derived fields (watts, effective_watts)
    are computed server-side and must NOT be sent by the client.
    """
    name:           str   = Field(..., min_length=1, max_length=120, description="Human-readable appliance name")
    cat:            str   = Field("medium", pattern="^(high|medium|low)$", description="Power category")
    voltage_v:      float = Field(120.0, ge=1.0,  le=480.0, description="Supply voltage in volts")
    current_a:      float = Field(1.0,   ge=0.01, le=200.0, description="Rated current draw in amperes")
    power_factor:   float = Field(0.95,  ge=0.1,  le=1.0,   description="cos φ — real/apparent power ratio")
    efficiency_pct: float = Field(90.0,  ge=1.0,  le=100.0, description="Combined device+inverter efficiency %")
    duty_cycle_pct: float = Field(100.0, ge=1.0,  le=100.0, description="% of active time the element is ON")
    hrs:            float = Field(4.0,   ge=0.1,  le=24.0,  description="Daily active hours window")
    sched:          str   = Field("24h",  description="Load schedule type (see simulation.py:app_duty)")
    on:             bool  = Field(True,   description="Whether appliance is currently enabled")
    icon:           str   = Field("🔌",  description="Emoji icon for UI display")
    clr:            str   = Field("#0A84FF", description="Hex color for UI display")

    @field_validator("name")
    @classmethod
    def name_strip(cls, v: str) -> str:
        return v.strip()


class ApplianceUpdate(BaseModel):
    """
    Body for PUT /api/appliances/{id}.
    All fields optional — only provided fields are updated (PATCH semantics).
    """
    name:           Optional[str]   = None
    cat:            Optional[str]   = None
    voltage_v:      Optional[float] = None
    current_a:      Optional[float] = None
    power_factor:   Optional[float] = None
    efficiency_pct: Optional[float] = None
    duty_cycle_pct: Optional[float] = None
    hrs:            Optional[float] = None
    sched:          Optional[str]   = None
    on:             Optional[bool]  = None
    icon:           Optional[str]   = None
    clr:            Optional[str]   = None


class ApplianceRead(BaseModel):
    """
    Full appliance record returned to the client.
    watts and effective_watts are server-computed derived fields.
    """
    id:             int
    name:           str
    cat:            str
    voltage_v:      float
    current_a:      float
    power_factor:   float
    efficiency_pct: float
    duty_cycle_pct: float
    hrs:            float
    watts:          float   # computed: V × A × PF
    effective_watts: float  # computed: watts / (efficiency_pct/100)
    on:             bool
    sched:          str
    icon:           str
    clr:            str
    is_custom:      bool
    created_at:     str
    updated_at:     str


class ToggleRequest(BaseModel):
    """Body for POST /api/appliances/{id}/toggle."""
    on: Optional[bool] = None  # If None, server flips current state


class ToggleResponse(BaseModel):
    id: int
    on: bool


# ─────────────────────────────────────────────────────────────────────────────
# SIMULATION SCHEMAS
# ─────────────────────────────────────────────────────────────────────────────

class SimulateRequest(BaseModel):
    """
    Body for POST /api/simulate.
    All fields are optional — defaults match the UI startup configuration.
    """
    battery_capacity_kwh: float = Field(45.0,  ge=5.0,  le=500.0)
    starting_soc:         float = Field(0.87,  ge=0.05, le=1.0)
    solar_output_kwh:     float = Field(2.0,   ge=0.0,  le=50.0)
    weather:              str   = Field("sunny", pattern="^(sunny|partly|overcast|rainy)$")
    scenario:             str   = Field("expected", pattern="^(expected|best|worst)$")
    occupants:            int   = Field(2,     ge=1, le=12)
    experience:           str   = Field("normal", pattern="^(expert|normal|new)$")
    load_factor:          float = Field(1.0,   ge=0.1, le=5.0)
    temperature_c:        float = Field(22.0,  ge=-30.0, le=55.0)
    irradiance_factor:    float = Field(1.0,   ge=0.0, le=2.0)
    # What-if override (multiplied into solar_output_kwh)
    solar_intensity:      Optional[float] = Field(None, ge=0.0, le=2.0)


class PillarBreakdown(BaseModel):
    """Four stability pillars that sum to the total score."""
    p1: float   # Energy Autonomy      (0 – 3.5)
    p1_max: float = 3.5
    p2: float   # Solar Self-Sufficiency (0 – 3.0)
    p2_max: float = 3.0
    p3: float   # Peak Safety Margin   (0 – 2.0)
    p3_max: float = 2.0
    p4: float   # Battery Reserve Floor (0 – 1.5)
    p4_max: float = 1.5


class ApplianceBreakdown(BaseModel):
    """Per-appliance energy contribution included in simulation response."""
    id:             int
    name:           str
    icon:           str
    cat:            str
    clr:            str
    watts:          float
    effective_watts: float
    voltage_v:      float
    current_a:      float
    power_factor:   float
    efficiency_pct: float
    duty_cycle_pct: float
    hrs:            float
    daily_kwh:      float
    share_pct:      float
    is_critical:    bool


class Alert(BaseModel):
    sev: str   # "info" | "warning" | "critical"
    msg: str


class Tip(BaseModel):
    gain: str
    msg:  str


class SimulateResponse(BaseModel):
    """
    Complete simulation result.
    This is the primary data contract between the Python engine and the
    JavaScript frontend.  Every field displayed on the dashboard maps to
    a field here.
    """
    # Battery state
    soc_pct:          int
    soc_kwh:          float
    bat_cap:          float
    bat_temp_factor:  float
    tte:              str      # Time-to-empty human readable
    tte_ok:           bool

    # Real-time (current hour)
    sol_now:  float
    ld_now:   float
    net_now:  float

    # Stability Index (0 – 10)
    si_score:   float
    si_grade:   str
    si_label:   str
    si_color:   str
    si_pillars: PillarBreakdown

    # Autonomy & energy balance
    days_off_grid:    float
    total_load_kwh:   float
    total_sol_kwh:    float
    bat_draw_kwh:     float
    min_soc:          float
    min_soc_h:        int
    peak_load_kw:     float
    sol_coverage_pct: float

    # Chart data (24 hourly buckets)
    sol_hourly:  list[float]
    load_hourly: list[float]
    soc_hourly:  list[float]
    net_hourly:  list[float]

    # Breakdown + alerts + tips
    breakdown: list[ApplianceBreakdown]
    alerts:    list[Alert]
    tips:      list[Tip]

    # Echo back config (used by UI to sync displayed settings)
    scenario:      str
    weather:       str
    occupants:     int
    experience:    str
    temperature_c: float

    # Performance
    ms: float


# ─────────────────────────────────────────────────────────────────────────────
# WEATHER SCHEMA
# ─────────────────────────────────────────────────────────────────────────────

class WeatherReading(BaseModel):
    """Body for POST /api/weather (called by frontend after Open-Meteo fetch)."""
    lat:          Optional[float] = None
    lon:          Optional[float] = None
    city:         Optional[str]   = None
    temp_c:       Optional[float] = None
    cloud_pct:    Optional[float] = None
    wind_kmh:     Optional[float] = None
    weather_code: Optional[int]   = None
    irr_factor:   Optional[float] = None
    wx_label:     Optional[str]   = None
    wx_icon:      Optional[str]   = None


class WeatherResponse(BaseModel):
    """Response from GET /api/weather — processed Open-Meteo data."""
    temp_c:       float
    cloud_pct:    float
    wind_kmh:     float
    weather_code: int
    wx:           str
    icon:         str
    lbl:          str
    irr_factor:   float
    city:         str


# ─────────────────────────────────────────────────────────────────────────────
# HEALTH SCHEMA
# ─────────────────────────────────────────────────────────────────────────────

class HealthResponse(BaseModel):
    status:     str
    version:    str
    db_path:    str
    appliances: int
    sync:       str
