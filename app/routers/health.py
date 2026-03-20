"""
app/routers/health.py
─────────────────────────────────────────────────────────────────────────────
Health check endpoint — used by load balancers, Docker health checks,
and monitoring systems to verify the service is alive and the database
is reachable.

Returns HTTP 200 when healthy, HTTP 503 when the database is unavailable.
"""
from fastapi import APIRouter
from fastapi.responses import JSONResponse

from app.database import get_db
from app.config import APP_VERSION, DB_PATH
from app.models import HealthResponse

router = APIRouter(prefix="/api", tags=["Health"])


@router.get("/health", response_model=HealthResponse, summary="Service health check")
async def health():
    """
    Returns service status and appliance count.
    Tests database connectivity by counting appliance rows.
    HTTP 503 if the database is unreachable.
    """
    try:
        async with get_db() as db:
            cur = await db.execute("SELECT COUNT(*) as n FROM appliances")
            row = await cur.fetchone()
            n   = row["n"]
    except Exception as exc:
        return JSONResponse(
            status_code=503,
            content={"status": "error", "detail": str(exc)},
        )
    return {
        "status":     "ok",
        "version":    APP_VERSION,
        "db_path":    DB_PATH,
        "appliances": n,
    }
