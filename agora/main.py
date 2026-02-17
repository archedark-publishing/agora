"""FastAPI entrypoint for Agora."""

import asyncio
import logging
from email.utils import format_datetime
from datetime import datetime, timedelta, timezone
from secrets import token_urlsafe
from urllib.parse import urlsplit
from typing import Any
from time import monotonic
from uuid import UUID

import httpx
from fastapi import Depends, FastAPI, Header, HTTPException, Query, Request, Response, status
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import Text, case, cast, func, not_, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from agora.config import get_settings
from agora.database import AsyncSessionLocal, close_engine, get_db_session, run_health_query
from agora.health_checker import run_health_check_cycle
from agora.models import Agent
from agora.query_tracker import QueryTracker
from agora.rate_limit import SlidingWindowRateLimiter
from agora.registry_export import build_registry_snapshot
from agora.security import hash_api_key, verify_api_key
from agora.stale import compute_agent_stale_metadata, stale_filter_expression
from agora.url_safety import (
    URLSafetyError,
    assert_url_safe_for_outbound,
    assert_url_safe_for_registration,
)
from agora.url_normalization import URLNormalizationError, normalize_url
from agora.validation import AgentCardValidationError, validate_agent_card

settings = get_settings()
logging.basicConfig(
    level=getattr(logging, settings.log_level.upper(), logging.INFO),
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
app = FastAPI(title=settings.app_name, version=settings.app_version)
started_at_monotonic = monotonic()
RATE_LIMIT_WINDOW_SECONDS = 3600
rate_limiter = SlidingWindowRateLimiter()
recovery_logger = logging.getLogger("agora.recovery")
health_logger = logging.getLogger("agora.health")
registry_logger = logging.getLogger("agora.registry")
request_logger = logging.getLogger("agora.request")
query_tracker = QueryTracker()
health_task: asyncio.Task[None] | None = None
registry_task: asyncio.Task[None] | None = None
latest_registry_snapshot: dict[str, Any] | None = None
request_metrics: dict[str, int] = {}
last_health_summary: dict[str, int] = {
    "checked_count": 0,
    "healthy_count": 0,
    "unhealthy_count": 0,
    "skipped_count": 0,
}
templates = Jinja2Templates(directory="agora/templates")


def _track_agent_query(agent_id: UUID) -> None:
    query_tracker.mark(agent_id)


async def _health_checker_loop() -> None:
    while True:
        try:
            summary = await run_health_check_cycle(
                AsyncSessionLocal,
                query_tracker,
                timeout_seconds=settings.outbound_http_timeout_seconds,
                allow_private_network_targets=settings.allow_private_network_targets,
            )
            health_logger.info(
                "health_cycle checked=%s healthy=%s unhealthy=%s skipped=%s",
                summary.checked_count,
                summary.healthy_count,
                summary.unhealthy_count,
                summary.skipped_count,
            )
            last_health_summary.update(
                {
                    "checked_count": summary.checked_count,
                    "healthy_count": summary.healthy_count,
                    "unhealthy_count": summary.unhealthy_count,
                    "skipped_count": summary.skipped_count,
                }
            )
        except Exception as exc:  # pragma: no cover - defensive background safety
            health_logger.exception("health_cycle_failed error=%s", exc)

        await asyncio.sleep(settings.health_check_interval)


async def _registry_refresh_loop() -> None:
    global latest_registry_snapshot
    while True:
        try:
            latest_registry_snapshot = await build_registry_snapshot(AsyncSessionLocal)
            registry_logger.info(
                "registry_snapshot_refreshed agents_count=%s generated_at=%s",
                latest_registry_snapshot["agents_count"],
                latest_registry_snapshot["generated_at"],
            )
        except Exception as exc:  # pragma: no cover - defensive background safety
            registry_logger.exception("registry_snapshot_failed error=%s", exc)

        await asyncio.sleep(settings.registry_refresh_interval)


@app.on_event("startup")
async def startup_event() -> None:
    global health_task, registry_task
    health_task = asyncio.create_task(_health_checker_loop())
    registry_task = asyncio.create_task(_registry_refresh_loop())


@app.middleware("http")
async def request_logging_middleware(request: Request, call_next: Any) -> Response:
    started = monotonic()
    path = request.url.path
    method = request.method
    try:
        response = await call_next(request)
    except Exception:
        latency_ms = int((monotonic() - started) * 1000)
        request_logger.exception(
            "request method=%s path=%s status=%s latency_ms=%s",
            method,
            path,
            500,
            latency_ms,
        )
        request_metrics[f"{method} {path} 500"] = request_metrics.get(f"{method} {path} 500", 0) + 1
        raise

    latency_ms = int((monotonic() - started) * 1000)
    request_logger.info(
        "request method=%s path=%s status=%s latency_ms=%s",
        method,
        path,
        response.status_code,
        latency_ms,
    )
    key = f"{method} {path} {response.status_code}"
    request_metrics[key] = request_metrics.get(key, 0) + 1
    return response


@app.on_event("shutdown")
async def shutdown_event() -> None:
    global health_task, registry_task
    if health_task:
        health_task.cancel()
        try:
            await health_task
        except asyncio.CancelledError:
            pass
        health_task = None
    if registry_task:
        registry_task.cancel()
        try:
            await registry_task
        except asyncio.CancelledError:
            pass
        registry_task = None
    await close_engine()


@app.get("/api/v1", tags=["meta"])
async def api_root() -> dict[str, str]:
    return {
        "name": settings.app_name,
        "version": settings.app_version,
        "status": "ok",
    }


@app.get("/", response_class=HTMLResponse, include_in_schema=False)
async def home_page(
    request: Request,
    session: AsyncSession = Depends(get_db_session),
) -> HTMLResponse:
    total_agents = int((await session.scalar(select(func.count(Agent.id)))) or 0)
    healthy_agents = int(
        (
            await session.scalar(
                select(func.count(Agent.id)).where(Agent.health_status == "healthy")
            )
        )
        or 0
    )
    recent_agents = list(
        (
            await session.scalars(
                select(Agent).order_by(Agent.registered_at.desc()).limit(8)
            )
        ).all()
    )

    now_utc = datetime.now(tz=timezone.utc)
    cards = []
    for agent in recent_agents:
        is_stale, stale_days = compute_agent_stale_metadata(agent, now=now_utc)
        cards.append(
            {
                "id": str(agent.id),
                "name": agent.name,
                "description": agent.description or "",
                "url": agent.url,
                "health_status": agent.health_status,
                "is_stale": is_stale,
                "stale_days": stale_days,
                "registered_at": agent.registered_at.isoformat(),
            }
        )

    return templates.TemplateResponse(
        "home.html",
        {
            "request": request,
            "stats": {
                "total_agents": total_agents,
                "healthy_agents": healthy_agents,
            },
            "recent_agents": cards,
        },
    )


@app.get("/search", response_class=HTMLResponse, include_in_schema=False)
async def search_page(
    request: Request,
    session: AsyncSession = Depends(get_db_session),
    q: str | None = Query(default=None),
    skill: str | None = Query(default=None),
    capability: str | None = Query(default=None),
    tag: str | None = Query(default=None),
    health: str | None = Query(default=None),
    stale: str | None = Query(default=None),
    limit: int = Query(default=20, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> HTMLResponse:
    skills = [item.strip() for item in (skill or "").split(",") if item.strip()]
    capabilities = [item.strip() for item in (capability or "").split(",") if item.strip()]
    tags = [item.strip() for item in (tag or "").split(",") if item.strip()]
    health_filters = [health] if health else None
    stale_bool: bool | None = None
    if stale == "true":
        stale_bool = True
    elif stale == "false":
        stale_bool = False

    results = await list_agents(
        request=request,
        session=session,
        skill=skills or None,
        capability=capabilities or None,
        tag=tags or None,
        health=health_filters,
        q=q,
        stale=stale_bool,
        limit=limit,
        offset=offset,
    )
    has_previous = offset > 0
    has_next = (offset + limit) < results["total"]

    return templates.TemplateResponse(
        "search.html",
        {
            "request": request,
            "results": results,
            "filters": {
                "q": q or "",
                "skill": skill or "",
                "capability": capability or "",
                "tag": tag or "",
                "health": health or "",
                "stale": stale or "",
                "limit": limit,
                "offset": offset,
            },
            "has_previous": has_previous,
            "has_next": has_next,
            "previous_offset": max(0, offset - limit),
            "next_offset": offset + limit,
        },
    )


def _build_verify_url(agent_url: str) -> str:
    """Return the recovery verification URL for an agent origin."""

    parts = urlsplit(agent_url)
    host = parts.hostname or ""
    port = parts.port
    if port and port != 443:
        return f"https://{host}:{port}/.well-known/agora-verify"
    return f"https://{host}/.well-known/agora-verify"


async def _fetch_recovery_token(verify_url: str) -> str:
    timeout = httpx.Timeout(settings.outbound_http_timeout_seconds)
    async with httpx.AsyncClient(timeout=timeout, follow_redirects=False) as client:
        response = await client.get(verify_url)
        response.raise_for_status()
        return response.text


def _client_ip(request: Request) -> str:
    return request.client.host if request.client else "unknown"


def _enforce_rate_limit(
    *,
    key: str,
    limit: int,
    window_seconds: int = RATE_LIMIT_WINDOW_SECONDS,
) -> None:
    result = rate_limiter.check(key=key, limit=limit, window_seconds=window_seconds)
    if result.allowed:
        return
    raise HTTPException(
        status_code=status.HTTP_429_TOO_MANY_REQUESTS,
        detail="Rate limit exceeded",
        headers={"Retry-After": str(result.retry_after_seconds)},
    )


def _enforce_recovery_rate_limits(request: Request, agent_id: UUID, action: str) -> None:
    ip = _client_ip(request)
    if action == "start":
        ip_limit = 5
        agent_limit = 3
    else:
        ip_limit = 10
        agent_limit = 5

    ip_result = rate_limiter.check(
        key=f"recovery:{action}:ip:{ip}",
        limit=ip_limit,
        window_seconds=RATE_LIMIT_WINDOW_SECONDS,
    )
    if not ip_result.allowed:
        recovery_logger.warning(
            "recovery_abuse action=%s agent_id=%s source_ip=%s outcome=rate_limited_ip retry_after=%s",
            action,
            agent_id,
            ip,
            ip_result.retry_after_seconds,
        )
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Rate limit exceeded",
            headers={"Retry-After": str(ip_result.retry_after_seconds)},
        )

    agent_result = rate_limiter.check(
        key=f"recovery:{action}:agent:{agent_id}",
        limit=agent_limit,
        window_seconds=RATE_LIMIT_WINDOW_SECONDS,
    )
    if not agent_result.allowed:
        recovery_logger.warning(
            "recovery_abuse action=%s agent_id=%s source_ip=%s outcome=rate_limited_agent retry_after=%s",
            action,
            agent_id,
            ip,
            agent_result.retry_after_seconds,
        )
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Rate limit exceeded",
            headers={"Retry-After": str(agent_result.retry_after_seconds)},
        )


@app.post("/api/v1/agents", status_code=status.HTTP_201_CREATED, tags=["agents"])
async def register_agent(
    agent_card_payload: dict[str, Any],
    request: Request,
    session: AsyncSession = Depends(get_db_session),
    api_key: str = Header(alias="X-API-Key", min_length=1),
) -> dict[str, str]:
    _enforce_rate_limit(
        key=f"api:post_agents:key:{hash_api_key(api_key)}",
        limit=10,
    )

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
    try:
        assert_url_safe_for_registration(
            normalized_url,
            allow_private=settings.allow_private_network_targets,
        )
    except URLSafetyError as exc:
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


@app.post("/api/v1/agents/{agent_id}/recovery/start", tags=["recovery"])
async def start_recovery(
    agent_id: UUID,
    request: Request,
    session: AsyncSession = Depends(get_db_session),
) -> dict[str, str]:
    _enforce_recovery_rate_limits(request, agent_id, action="start")
    agent = await session.get(Agent, agent_id)
    if agent is None:
        recovery_logger.info(
            "recovery_abuse action=start agent_id=%s source_ip=%s outcome=not_found",
            agent_id,
            _client_ip(request),
        )
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Agent not found")

    challenge_token = token_urlsafe(32)
    now_utc = datetime.now(tz=timezone.utc)
    expires_at = now_utc + timedelta(seconds=settings.recovery_challenge_ttl_seconds)

    # Enforces single active challenge by replacing the prior hash/metadata.
    agent.recovery_challenge_hash = hash_api_key(challenge_token)
    agent.recovery_challenge_created_at = now_utc
    agent.recovery_challenge_expires_at = expires_at
    await session.commit()
    recovery_logger.info(
        "recovery_abuse action=start agent_id=%s source_ip=%s outcome=challenge_issued",
        agent_id,
        _client_ip(request),
    )

    return {
        "agent_id": str(agent.id),
        "challenge_token": challenge_token,
        "verify_url": _build_verify_url(agent.url),
        "expires_at": expires_at.isoformat(),
    }


@app.post("/api/v1/agents/{agent_id}/recovery/complete", tags=["recovery"])
async def complete_recovery(
    agent_id: UUID,
    request: Request,
    session: AsyncSession = Depends(get_db_session),
    api_key: str = Header(alias="X-API-Key", min_length=1),
) -> dict[str, str]:
    _enforce_recovery_rate_limits(request, agent_id, action="complete")
    agent = await session.get(Agent, agent_id)
    if agent is None:
        recovery_logger.info(
            "recovery_abuse action=complete agent_id=%s source_ip=%s outcome=not_found",
            agent_id,
            _client_ip(request),
        )
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Agent not found")

    now_utc = datetime.now(tz=timezone.utc)
    if (
        agent.recovery_challenge_hash is None
        or agent.recovery_challenge_expires_at is None
        or agent.recovery_challenge_expires_at <= now_utc
    ):
        recovery_logger.info(
            "recovery_abuse action=complete agent_id=%s source_ip=%s outcome=no_active_or_expired",
            agent_id,
            _client_ip(request),
        )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No active recovery challenge or challenge expired",
        )

    verify_url = _build_verify_url(agent.url)
    try:
        assert_url_safe_for_outbound(
            verify_url,
            allow_private=settings.allow_private_network_targets,
        )
        fetched_token = await _fetch_recovery_token(verify_url)
    except httpx.HTTPError as exc:
        recovery_logger.info(
            "recovery_abuse action=complete agent_id=%s source_ip=%s outcome=verify_unreachable",
            agent_id,
            _client_ip(request),
        )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Recovery verification endpoint unreachable or invalid",
        ) from exc
    except URLSafetyError as exc:
        recovery_logger.info(
            "recovery_abuse action=complete agent_id=%s source_ip=%s outcome=unsafe_target",
            agent_id,
            _client_ip(request),
        )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc

    if not verify_api_key(fetched_token, agent.recovery_challenge_hash):
        recovery_logger.info(
            "recovery_abuse action=complete agent_id=%s source_ip=%s outcome=verification_mismatch",
            agent_id,
            _client_ip(request),
        )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Recovery challenge verification mismatch",
        )

    agent.owner_key_hash = hash_api_key(api_key)
    agent.recovery_challenge_hash = None
    agent.recovery_challenge_created_at = None
    agent.recovery_challenge_expires_at = None
    await session.commit()
    recovery_logger.info(
        "recovery_abuse action=complete agent_id=%s source_ip=%s outcome=success",
        agent_id,
        _client_ip(request),
    )

    return {
        "agent_id": str(agent.id),
        "message": "Recovery complete and API key rotated",
    }


@app.get("/api/v1/agents/{agent_id}", tags=["agents"])
async def get_agent_detail(
    agent_id: UUID,
    session: AsyncSession = Depends(get_db_session),
) -> dict[str, Any]:
    agent = await session.get(Agent, agent_id)
    if agent is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Agent not found")

    _track_agent_query(agent.id)
    is_stale, stale_days = compute_agent_stale_metadata(agent)
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
    request: Request,
    session: AsyncSession = Depends(get_db_session),
    api_key: str = Header(alias="X-API-Key", min_length=1),
) -> dict[str, str]:
    _enforce_rate_limit(
        key=f"api:put_agent:key:{hash_api_key(api_key)}",
        limit=20,
    )

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
    try:
        assert_url_safe_for_registration(
            normalized_url,
            allow_private=settings.allow_private_network_targets,
        )
    except URLSafetyError as exc:
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
    request: Request,
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
    api_key = request.headers.get("X-API-Key")
    if api_key:
        _enforce_rate_limit(
            key=f"api:get_agents:key:{hash_api_key(api_key)}",
            limit=1000,
        )
    else:
        _enforce_rate_limit(
            key=f"api:get_agents:ip:{_client_ip(request)}",
            limit=100,
        )

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
    stale_expr = stale_filter_expression(now_utc)
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
    for agent in agents:
        _track_agent_query(agent.id)

    response_agents: list[dict[str, Any]] = []
    for agent in agents:
        is_stale, stale_days = compute_agent_stale_metadata(agent, now=now_utc)
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


@app.get("/api/v1/admin/stale-candidates", tags=["admin"])
async def stale_candidates_report(
    session: AsyncSession = Depends(get_db_session),
    admin_token: str | None = Header(default=None, alias="X-Admin-Token"),
) -> dict[str, Any]:
    if settings.admin_api_token is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Endpoint not configured")
    if admin_token != settings.admin_api_token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid admin token")

    now_utc = datetime.now(tz=timezone.utc)
    stale_expr = stale_filter_expression(now_utc)
    agents = list(
        (
            await session.scalars(
                select(Agent).where(stale_expr).order_by(Agent.registered_at.desc())
            )
        ).all()
    )
    candidates = []
    for agent in agents:
        is_stale, stale_days = compute_agent_stale_metadata(agent, now=now_utc)
        candidates.append(
            {
                "id": str(agent.id),
                "name": agent.name,
                "url": agent.url,
                "health_status": agent.health_status,
                "is_stale": is_stale,
                "stale_days": stale_days,
                "registered_at": agent.registered_at.isoformat(),
                "last_healthy_at": (
                    agent.last_healthy_at.isoformat() if agent.last_healthy_at else None
                ),
            }
        )

    return {
        "generated_at": now_utc.isoformat(),
        "count": len(candidates),
        "candidates": candidates,
    }


@app.delete("/api/v1/agents/{agent_id}", status_code=status.HTTP_204_NO_CONTENT, tags=["agents"])
async def delete_agent(
    agent_id: UUID,
    request: Request,
    session: AsyncSession = Depends(get_db_session),
    api_key: str = Header(alias="X-API-Key", min_length=1),
) -> Response:
    _enforce_rate_limit(
        key=f"api:delete_agent:key:{hash_api_key(api_key)}",
        limit=10,
    )

    agent = await session.get(Agent, agent_id)
    if agent is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Agent not found")

    if not verify_api_key(api_key, agent.owner_key_hash):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid API key")

    await session.delete(agent)
    await session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@app.get("/api/v1/registry.json", tags=["registry"])
async def registry_export(request: Request) -> JSONResponse:
    global latest_registry_snapshot
    _enforce_rate_limit(
        key=f"api:get_registry:ip:{_client_ip(request)}",
        limit=10,
    )

    if latest_registry_snapshot is None:
        latest_registry_snapshot = await build_registry_snapshot(AsyncSessionLocal)

    generated_at = latest_registry_snapshot.get("generated_at", "")
    agents_count = latest_registry_snapshot.get("agents_count", 0)
    generated_dt = datetime.fromisoformat(generated_at) if generated_at else datetime.now(tz=timezone.utc)
    etag = f"\"{generated_at}:{agents_count}\""

    return JSONResponse(
        content=latest_registry_snapshot,
        headers={
            "Cache-Control": "public, max-age=300, stale-while-revalidate=120",
            "ETag": etag,
            "Last-Modified": format_datetime(generated_dt, usegmt=True),
        },
    )


@app.get("/api/v1/metrics", tags=["observability"])
async def metrics() -> dict[str, Any]:
    return {
        "request_metrics": request_metrics,
        "health_summary": last_health_summary,
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
