"""FastAPI entrypoint for Agora."""

from datetime import datetime, timedelta, timezone
from typing import Any
from time import monotonic
from uuid import UUID

from fastapi import Depends, FastAPI, Header, HTTPException, Query, status
from sqlalchemy import Text, and_, case, cast, func, not_, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from agora.config import get_settings
from agora.database import close_engine, get_db_session, run_health_query
from agora.models import Agent
from agora.security import hash_api_key, verify_api_key
from agora.url_normalization import URLNormalizationError, normalize_url
from agora.validation import AgentCardValidationError, validate_agent_card

settings = get_settings()
app = FastAPI(title=settings.app_name, version=settings.app_version)
started_at_monotonic = monotonic()
STALE_THRESHOLD_DAYS = 7


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


def _compute_stale_metadata(agent: Agent, now: datetime | None = None) -> tuple[bool, int]:
    if agent.health_status != "unhealthy":
        return False, 0

    reference = agent.last_healthy_at or agent.registered_at
    now_utc = now or datetime.now(tz=timezone.utc)
    elapsed = now_utc - reference
    is_stale = elapsed > timedelta(days=STALE_THRESHOLD_DAYS)
    return is_stale, elapsed.days if is_stale else 0


def _stale_filter_expression(now: datetime) -> Any:
    stale_cutoff = now - timedelta(days=STALE_THRESHOLD_DAYS)
    return and_(
        Agent.health_status == "unhealthy",
        or_(
            and_(Agent.last_healthy_at.is_not(None), Agent.last_healthy_at < stale_cutoff),
            and_(Agent.last_healthy_at.is_(None), Agent.registered_at < stale_cutoff),
        ),
    )


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
        owner_key_hash=hash_api_key(api_key),
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


@app.get("/api/v1/agents/{agent_id}", tags=["agents"])
async def get_agent_detail(
    agent_id: UUID,
    session: AsyncSession = Depends(get_db_session),
) -> dict[str, Any]:
    agent = await session.get(Agent, agent_id)
    if agent is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Agent not found")

    is_stale, stale_days = _compute_stale_metadata(agent)
    return {
        "id": str(agent.id),
        "agent_card": agent.agent_card,
        "health_status": agent.health_status,
        "last_health_check": agent.last_health_check.isoformat() if agent.last_health_check else None,
        "last_healthy_at": agent.last_healthy_at.isoformat() if agent.last_healthy_at else None,
        "registered_at": agent.registered_at.isoformat(),
        "updated_at": agent.updated_at.isoformat(),
        "is_stale": is_stale,
        "stale_days": stale_days,
    }


@app.put("/api/v1/agents/{agent_id}", tags=["agents"])
async def update_agent(
    agent_id: UUID,
    agent_card_payload: dict[str, Any],
    session: AsyncSession = Depends(get_db_session),
    api_key: str = Header(alias="X-API-Key", min_length=1),
) -> dict[str, str]:
    agent = await session.get(Agent, agent_id)
    if agent is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Agent not found")

    if not verify_api_key(api_key, agent.owner_key_hash):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid API key")

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

    if normalized_url != agent.url:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Agent URL is immutable and cannot be changed",
        )

    normalized_card = validated.card.model_dump(by_alias=True, mode="json")
    normalized_card["url"] = normalized_url

    agent.name = validated.card.name
    agent.description = validated.card.description
    agent.version = validated.card.version
    agent.protocol_version = validated.card.protocol_version
    agent.agent_card = normalized_card
    agent.skills = validated.skills
    agent.capabilities = validated.capabilities
    agent.tags = validated.tags
    agent.input_modes = validated.input_modes
    agent.output_modes = validated.output_modes
    await session.commit()
    await session.refresh(agent)

    return {
        "id": str(agent.id),
        "name": agent.name,
        "url": agent.url,
        "updated_at": agent.updated_at.isoformat(),
        "message": "Agent updated successfully",
    }


@app.get("/api/v1/agents", tags=["agents"])
async def list_agents(
    session: AsyncSession = Depends(get_db_session),
    skill: list[str] | None = Query(default=None),
    capability: list[str] | None = Query(default=None),
    tag: list[str] | None = Query(default=None),
    health: list[str] | None = Query(default=None),
    q: str | None = Query(default=None),
    stale: bool | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> dict[str, Any]:
    filters: list[Any] = []
    if skill:
        filters.append(Agent.skills.overlap(skill))
    if capability:
        filters.append(Agent.capabilities.overlap(capability))
    if tag:
        filters.append(Agent.tags.overlap(tag))

    if health:
        allowed_health_values = {"healthy", "unhealthy", "unknown"}
        invalid_values = [value for value in health if value not in allowed_health_values]
        if invalid_values:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid health value(s): {', '.join(invalid_values)}",
            )
        filters.append(Agent.health_status.in_(health))

    if q:
        query_like = f"%{q}%"
        filters.append(
            or_(
                Agent.name.ilike(query_like),
                Agent.description.ilike(query_like),
                cast(Agent.skills, Text).ilike(query_like),
                cast(Agent.tags, Text).ilike(query_like),
            )
        )

    now_utc = datetime.now(tz=timezone.utc)
    stale_expr = _stale_filter_expression(now_utc)
    if stale is True:
        filters.append(stale_expr)
    elif stale is False:
        filters.append(not_(stale_expr))

    base_query = select(Agent)
    if filters:
        base_query = base_query.where(*filters)

    total_query = select(func.count()).select_from(base_query.subquery())
    total = int((await session.scalar(total_query)) or 0)

    ordered_query = (
        base_query.order_by(
            case(
                (Agent.health_status == "healthy", 0),
                (Agent.health_status == "unknown", 1),
                (Agent.health_status == "unhealthy", 2),
                else_=3,
            ),
            Agent.registered_at.desc(),
        )
        .limit(limit)
        .offset(offset)
    )
    agents = list((await session.scalars(ordered_query)).all())

    response_agents: list[dict[str, Any]] = []
    for agent in agents:
        is_stale, stale_days = _compute_stale_metadata(agent, now=now_utc)
        response_agents.append(
            {
                "id": str(agent.id),
                "name": agent.name,
                "description": agent.description,
                "url": agent.url,
                "version": agent.version,
                "skills": agent.skills or [],
                "capabilities": agent.capabilities or [],
                "health_status": agent.health_status,
                "registered_at": agent.registered_at.isoformat(),
                "is_stale": is_stale,
                "stale_days": stale_days,
            }
        )

    return {
        "agents": response_agents,
        "total": total,
        "limit": limit,
        "offset": offset,
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
        agents_count = int((await session.scalar(select(func.count(Agent.id)))) or 0)
    except Exception:
        return {
            "status": "unhealthy",
            "version": settings.app_version,
            "agents_count": 0,
            "uptime_seconds": int(monotonic() - started_at_monotonic),
        }

    return {
        "status": "healthy",
        "version": settings.app_version,
        "agents_count": agents_count,
        "uptime_seconds": int(monotonic() - started_at_monotonic),
    }
