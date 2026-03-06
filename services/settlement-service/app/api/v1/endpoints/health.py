from datetime import datetime, timezone

from fastapi import APIRouter, status
from sqlalchemy import text

from app.core.logging import get_logger
from app.db.session import AsyncSessionLocal
from app.schemas.settlement import HealthResponse

logger = get_logger(__name__)
router = APIRouter(prefix="/health", tags=["Health"])

_START_TIME = datetime.now(timezone.utc)

@router.get(
    "",
    response_model=HealthResponse,
    summary="Liveness probe",
    status_code=status.HTTP_200_OK,
    include_in_schema=False,
)
async def liveness() -> HealthResponse:

    return HealthResponse(
        status="ok",
        service="settlement-service",
        timestamp=datetime.now(timezone.utc),
    )

@router.get(
    "/ready",
    summary="Readiness probe",
    status_code=status.HTTP_200_OK,
    include_in_schema=False,
)
async def readiness() -> dict:

    checks: dict[str, str] = {}

    try:
        async with AsyncSessionLocal() as session:
            await session.execute(text("SELECT 1"))
        checks["database"] = "ok"
    except Exception as exc:
        logger.warning("Database health check failed", extra={"error": str(exc)})
        checks["database"] = "error"

    healthy = all(v == "ok" for v in checks.values())
    http_status = status.HTTP_200_OK if healthy else status.HTTP_503_SERVICE_UNAVAILABLE

    from fastapi.responses import JSONResponse

    return JSONResponse(
        status_code=http_status,
        content={
            "status": "ready" if healthy else "not_ready",
            "checks": checks,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        },
    )
