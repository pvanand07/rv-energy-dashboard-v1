"""
app/routers/appliances.py
─────────────────────────────────────────────────────────────────────────────
FastAPI router — appliance CRUD endpoints.

ENDPOINT SUMMARY
────────────────
  GET    /api/appliances           → list all appliances
  POST   /api/appliances           → create new appliance
  GET    /api/appliances/{id}      → get one appliance
  PUT    /api/appliances/{id}      → update appliance (partial)
  DELETE /api/appliances/{id}      → delete appliance
  POST   /api/appliances/{id}/toggle → toggle on/off state

All write operations persist to SQLite via app/crud.py.
Pydantic models in app/models.py validate inputs and shape responses.
"""
from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse

from app.database import get_db
from app.models import ApplianceCreate, ApplianceRead, ApplianceUpdate, ToggleRequest, ToggleResponse
from app import crud

router = APIRouter(prefix="/api/appliances", tags=["Appliances"])


@router.get("", response_model=list[ApplianceRead], summary="List all appliances")
async def list_appliances():
    """
    Return all appliances sorted by category (high → medium → low) then name.
    This is the primary data source for both the UI table and the simulation.
    """
    async with get_db() as db:
        return await crud.get_appliances(db)


@router.get("/{aid}", response_model=ApplianceRead, summary="Get appliance by ID")
async def get_appliance(aid: int):
    """Fetch a single appliance record by primary key."""
    async with get_db() as db:
        item = await crud.get_appliance_by_id(db, aid)
    if item is None:
        raise HTTPException(status_code=404, detail=f"Appliance {aid} not found")
    return item


@router.post("", response_model=ApplianceRead, status_code=201, summary="Create appliance")
async def create_appliance(data: ApplianceCreate):
    """
    Create a new appliance.

    Server-side computation:
      watts           = voltage_v × current_a × power_factor
      effective_watts = watts / (efficiency_pct / 100)

    These derived fields are stored and returned — the client never
    needs to compute them.
    """
    async with get_db() as db:
        return await crud.create_appliance(db, data)


@router.put("/{aid}", response_model=ApplianceRead, summary="Update appliance")
async def update_appliance(aid: int, data: ApplianceUpdate):
    """
    Partial update (PATCH semantics via PUT).
    Only fields included in the body are updated.
    Derived electrical fields are recomputed if any input changes.
    """
    async with get_db() as db:
        return await crud.update_appliance(db, aid, data)


@router.delete("/{aid}", summary="Delete appliance")
async def delete_appliance(aid: int):
    """
    Permanently delete an appliance.
    Historical simulation snapshots are preserved (soft reference).
    """
    async with get_db() as db:
        deleted_id = await crud.delete_appliance(db, aid)
    return {"deleted": deleted_id}


@router.post("/{aid}/toggle", response_model=ToggleResponse, summary="Toggle appliance on/off")
async def toggle_appliance(aid: int, body: ToggleRequest):
    """
    Enable or disable an appliance.
    If `on` is omitted, the current state is flipped.
    The frontend calls this when the user clicks the toggle switch.
    """
    async with get_db() as db:
        result = await crud.toggle_appliance(db, aid, body.on)
    return result
