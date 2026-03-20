"""
app/routers/pages.py
─────────────────────────────────────────────────────────────────────────────
Serves the single-page HTML application.

The frontend is a server-rendered Jinja2 template (templates/index.html).
On first load the server runs the default simulation and injects the result
as JSON into the page so the dashboard is fully populated without a
client-side fetch on load.

FastAPI's Jinja2Templates requires the `request` object to be passed in the
template context (used internally by Jinja2 for URL generation).
"""
from fastapi import APIRouter, Request
from fastapi.templating import Jinja2Templates
from markupsafe import Markup
import json as _json

from app.database import get_db
from app import crud
from app.simulation import run_simulation
from app.config import DEFAULT_BATTERY_KWH, DEFAULT_SOLAR_KWH, DEFAULT_START_SOC

router_pages = APIRouter(tags=["Pages"])
templates    = Jinja2Templates(directory="templates")

# Register tojson filter — Markup() prevents Jinja2 from HTML-escaping the JSON,
# which would turn " into &#34; and break the JavaScript const IDAT = {...}
templates.env.filters["tojson"] = lambda v: Markup(_json.dumps(v, ensure_ascii=False))


@router_pages.get("/", include_in_schema=False)
async def index(request: Request):
    """Serve the React/HTML single-page app with initial simulation data."""
    async with get_db() as db:
        apps = await crud.get_appliances(db)

    result = run_simulation({
        "appliances":          apps,
        "battery_capacity_kwh": DEFAULT_BATTERY_KWH,
        "starting_soc":         DEFAULT_START_SOC,
        "solar_output_kwh":     DEFAULT_SOLAR_KWH,
        "weather":              "sunny",
        "scenario":             "expected",
        "occupants":            2,
        "experience":           "normal",
        "load_factor":          1.0,
        "temperature_c":        22.0,
        "irradiance_factor":    1.0,
    })
    return templates.TemplateResponse(request, "index.html", {"d": result})
