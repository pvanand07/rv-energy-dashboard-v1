from fastapi import APIRouter
from datetime import datetime, timezone

router = APIRouter(prefix="/api", tags=["Test"])


@router.get("/test", summary="Test endpoint")
async def test():
    """Returns a simple OK response with a timestamp."""
    return {"status": "ok", "message": "test endpoint working", "timestamp": datetime.now(timezone.utc).isoformat()}
