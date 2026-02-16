"""FastAPI entrypoint for Agora."""

from datetime import datetime, timezone
from time import monotonic

from fastapi import Depends, FastAPI, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from agora.config import get_settings
from agora.database import close_engine, get_db_session, run_health_query

settings = get_settings()
app = FastAPI(title=settings.app_name, version=settings.app_version)
started_at_monotonic = monotonic()


@app.on_event("shutdown")
async def shutdown_event() -> None:
    await close_engine()


@app.get("/", tags=["meta"])
async def root() -> dict[str, str]:
    return {
        "name": settings.app_name,
        "version": settings.app_version,
        "status": "ok",
    }


@app.get("/api/v1/health/db", tags=["health"])
async def database_health_check(
    session: AsyncSession = Depends(get_db_session),
) -> dict[str, str]:
    try:
        await run_health_query(session)
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Database is unavailable",
        ) from exc

    return {
        "status": "healthy",
        "database": "ok",
        "checked_at": datetime.now(tz=timezone.utc).isoformat(),
    }


@app.get("/api/v1/health", tags=["health"])
async def basic_health(
    session: AsyncSession = Depends(get_db_session),
) -> dict[str, int | str]:
    try:
        await run_health_query(session)
    except Exception:
        return {
            "status": "unhealthy",
            "version": settings.app_version,
            "uptime_seconds": int(monotonic() - started_at_monotonic),
        }

    return {
        "status": "healthy",
        "version": settings.app_version,
        "uptime_seconds": int(monotonic() - started_at_monotonic),
    }
