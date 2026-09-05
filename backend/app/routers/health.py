from datetime import datetime, timezone

from fastapi import APIRouter

from app.db import get_pool

router = APIRouter(tags=["health"])


@router.get("/health")
def health() -> dict:
    checks: dict = {"app": "ok"}
    try:
        with get_pool().connection() as conn:
            row = conn.execute("SELECT 1").fetchone()
        checks["database"] = "ok" if row else "error"
    except Exception as e:
        checks["database"] = f"error: {type(e).__name__}"
    return {
        "status": "ok" if all(v == "ok" for v in checks.values()) else "degraded",
        "checks": checks,
        "time": datetime.now(timezone.utc).isoformat(),
    }
