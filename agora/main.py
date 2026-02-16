"""FastAPI entrypoint for Agora."""

from hashlib import sha256
from typing import Any
from datetime import datetime, timezone
from time import monotonic

from fastapi import Depends, FastAPI, Header, HTTPException, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from agora.config import get_settings
from agora.database import close_engine, get_db_session, run_health_query
from agora.models import Agent
from agora.url_normalization import URLNormalizationError, normalize_url
from agora.validation import AgentCardValidationError, validate_agent_card

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


def _hash_api_key(api_key: str) -> str:
    return sha256(api_key.encode("utf-8")).hexdigest()


@app.post("/api/v1/agents", status_code=status.HTTP_201_CREATED, tags=["agents"])
async def register_agent(
    agent_card_payload: dict[str, Any],
    session: AsyncSession = Depends(get_db_session),
    api_key: str = Header(alias="X-API-Key", min_length=1),
) -> dict[str, str]:
    try:
        validated = validate_agent_card(agent_card_payload)
    except AgentCardValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "message": "Invalid Agent Card",
                "errors": exc.errors,
            },
        ) from exc

    try:
        normalized_url = normalize_url(str(validated.card.url))
    except URLNormalizationError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "message": "Invalid Agent Card",
                "errors": [
                    {
                        "field": "url",
                        "message": str(exc),
                        "type": "value_error.url",
                    }
                ],
            },
        ) from exc

    existing_agent_id = await session.scalar(
        select(Agent.id).where(Agent.url == normalized_url).limit(1)
    )
    if existing_agent_id:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Agent with this URL already exists",
        )

    normalized_card = validated.card.model_dump(by_alias=True, mode="json")
    normalized_card["url"] = normalized_url

    agent = Agent(
        name=validated.card.name,
        description=validated.card.description,
        url=normalized_url,
        version=validated.card.version,
        protocol_version=validated.card.protocol_version,
        agent_card=normalized_card,
        skills=validated.skills,
        capabilities=validated.capabilities,
        tags=validated.tags,
        input_modes=validated.input_modes,
        output_modes=validated.output_modes,
        owner_key_hash=_hash_api_key(api_key),
    )
    session.add(agent)
    try:
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Agent with this URL already exists",
        ) from exc

    await session.refresh(agent)
    return {
        "id": str(agent.id),
        "name": agent.name,
        "url": agent.url,
        "registered_at": agent.registered_at.isoformat(),
        "message": "Agent registered successfully",
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
