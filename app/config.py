"""
app/config.py
─────────────────────────────────────────────────────────────────────────────
Central configuration via environment variables with sensible defaults.
Override any setting by setting the corresponding environment variable before
launching:

    DB_PATH=./prod.db uvicorn main:app --port 8080

All settings are read once at import time. Production deployments should
use a .env file or container secrets instead of inline values.
"""
import os
from pathlib import Path

# ── Project root ──────────────────────────────────────────────────────────
ROOT_DIR  = Path(__file__).resolve().parent.parent
DATA_DIR  = ROOT_DIR / "data"
DATA_DIR.mkdir(parents=True, exist_ok=True)

# ── Database ──────────────────────────────────────────────────────────────
DB_PATH: str = os.getenv("DB_PATH", str(DATA_DIR / "rv_energy.db"))
"""
Path to the SQLite database file.
SQLite is chosen for:
  • Zero-config deployment (no separate database server)
  • File portability (copy the .db file to move all data)
  • Sufficient performance for single-RV or small-fleet use cases
  • WAL mode enables concurrent reads during write operations

Scale path: swap aiosqlite for asyncpg + PostgreSQL when multi-RV fleet
           telemetry requires concurrent writes from multiple devices.
"""

# ── Server ────────────────────────────────────────────────────────────────
HOST: str = os.getenv("HOST", "0.0.0.0")
PORT: int = int(os.getenv("PORT", "5000"))
DEBUG: bool = os.getenv("DEBUG", "true").lower() == "true"

# ── Application ───────────────────────────────────────────────────────────
APP_TITLE:   str = "RV Energy Intelligence"
APP_VERSION: str = "2.1.0"
APP_TAGLINE: str = "Elevatics AI | Apple Design Edition"

# ── Simulation constants ──────────────────────────────────────────────────
STEPS: int   = 2880          # Simulation steps per day (one every 30 seconds)
DT_H:  float = 30 / 3600    # Hours per step = 0.008̄ h
DEFAULT_BATTERY_KWH:  float = 45.0   # Default LiFePO4 pack size (kWh)
DEFAULT_SOLAR_KWH:    float = 2.0    # Default panel daily output (kWh)
DEFAULT_START_SOC:    float = 0.87   # Default starting state-of-charge
INVERTER_LIMIT_KW:    float = 5.0    # Reference inverter ceiling for P3 pillar
AUTONOMY_BENCHMARK_D: float = 14.0  # Days considered "gold standard" for P1 pillar
SAFE_SOC_FLOOR:       float = 20.0  # LiFePO4 minimum safe SOC % for P4 pillar

# ── Simulation factor lookup tables ──────────────────────────────────────
WEATHER_FACTOR: dict[str, float] = {
    "sunny":    1.00,
    "partly":   0.60,
    "overcast": 0.25,
    "rainy":    0.05,
}
EXPERIENCE_FACTOR: dict[str, float] = {
    "expert": 0.85,   # Experts use 15% less energy through habit
    "normal": 1.00,
    "new":    1.20,   # New RVers use 20% more energy than rated
}
SCENARIO_LOAD_FACTOR: dict[str, float] = {
    "expected": 1.00,
    "best":     0.78,   # 22% lower load (conservative day)
    "worst":    1.28,   # 28% higher load (heavy usage day)
}
SCENARIO_SOLAR_FACTOR: dict[str, float] = {
    "expected": 1.00,
    "best":     1.22,   # 22% higher solar (optimal panel angle, clean panels)
    "worst":    0.65,   # 35% lower solar (suboptimal conditions)
}
