"""FastAPI entrypoint for Agora."""

import asyncio
import hmac
import ipaddress
import logging
from datetime import datetime, timedelta, timezone
from email.utils import format_datetime
from secrets import token_urlsafe
from textwrap import dedent
from time import monotonic
from typing import Any
from urllib.parse import urlsplit
from uuid import UUID

import httpx
from fastapi import Depends, FastAPI, Form, Header, HTTPException, Query, Request, Response, status
from fastapi.responses import HTMLResponse, JSONResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles
from fastapi.routing import APIRoute
from fastapi.templating import Jinja2Templates
from sqlalchemy import Text, case, cast, func, not_, or_, select, update
from sqlalchemy.exc import DBAPIError, DataError, IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from agora.config import get_settings
from agora.database import AsyncSessionLocal, close_engine, get_db_session, run_health_query
from agora.health_checker import run_health_check_cycle
from agora.metrics import BoundedRequestMetrics
from agora.models import Agent
from agora.query_tracker import QueryTracker
from agora.rate_limit import RateLimitBackendError, create_rate_limiter
from agora.registry_export import build_registry_snapshot
from agora.sanitization import sanitize_json_strings, sanitize_ui_text
from agora.security import (
    api_key_fingerprint,
    hash_api_key,
    should_rehash_api_key_hash,
    verify_api_key,
)
from agora.stale import compute_agent_stale_metadata, stale_filter_expression
from agora.url_normalization import URLNormalizationError, normalize_url
from agora.url_safety import (
    URLSafetyError,
    assert_url_safe_for_outbound,
    assert_url_safe_for_registration,
    pin_hostname_resolution,
)
from agora.validation import AgentCardValidationError, validate_agent_card

settings = get_settings()
logging.basicConfig(
    level=getattr(logging, settings.log_level.upper(), logging.INFO),
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
app = FastAPI(title=settings.app_name, version=settings.app_version)
app.mount("/static", StaticFiles(directory="agora/static"), name="static")
started_at_monotonic = monotonic()
RATE_LIMIT_WINDOW_SECONDS = 3600
rate_limit_logger = logging.getLogger("agora.rate_limit")
rate_limiter, rate_limiter_is_shared = create_rate_limiter(
    backend=settings.rate_limit_backend,
    redis_url=settings.redis_url,
    prefix=settings.rate_limit_prefix,
    logger=rate_limit_logger,
)
if settings.environment.lower() not in {"development", "test"} and not rate_limiter_is_shared:
    raise RuntimeError(
        "Shared rate limiting is required outside development/test. "
        "Configure REDIS_URL or RATE_LIMIT_BACKEND=redis."
    )
recovery_logger = logging.getLogger("agora.recovery")
health_logger = logging.getLogger("agora.health")
registry_logger = logging.getLogger("agora.registry")
request_logger = logging.getLogger("agora.request")
query_tracker = QueryTracker()
health_task: asyncio.Task[None] | None = None
registry_task: asyncio.Task[None] | None = None
latest_registry_snapshot: dict[str, Any] | None = None
request_metrics = BoundedRequestMetrics(max_entries=settings.metrics_max_entries)
last_health_summary: dict[str, int] = {
    "checked_count": 0,
    "healthy_count": 0,
    "unhealthy_count": 0,
    "skipped_count": 0,
}
templates = Jinja2Templates(directory="agora/templates")


def _track_agent_query(agent_id: UUID) -> None:
    query_tracker.mark(agent_id)


def _metric_route_label(request: Request) -> str:
    route = request.scope.get("route")
    if isinstance(route, APIRoute):
        return route.path
    return "_unmatched"


async def _require_admin_token(
    request: Request,
    admin_token: str | None,
    *,
    scope: str,
) -> None:
    if settings.admin_api_token is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Endpoint not configured")
    await _enforce_admin_rate_limits(request, scope=scope)
    if not hmac.compare_digest(admin_token or "", settings.admin_api_token):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid admin token")


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
async def request_size_limit_middleware(request: Request, call_next: Any) -> Response:
    limit = settings.max_request_body_bytes
    if limit > 0 and request.method.upper() not in {"GET", "HEAD", "OPTIONS"}:
        content_length = request.headers.get("content-length")
        if content_length is not None:
            try:
                declared_size = int(content_length)
            except ValueError:
                return JSONResponse(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    content={"detail": "Invalid Content-Length header"},
                )
            if declared_size > limit:
                return JSONResponse(
                    status_code=status.HTTP_413_CONTENT_TOO_LARGE,
                    content={"detail": "Request payload too large"},
                )

    return await call_next(request)


@app.middleware("http")
async def request_logging_middleware(request: Request, call_next: Any) -> Response:
    started = monotonic()
    path = request.url.path
    method = request.method.upper()
    try:
        response = await call_next(request)
    except Exception:
        latency_ms = int((monotonic() - started) * 1000)
        route_label = _metric_route_label(request)
        request_logger.exception(
            "request method=%s path=%s status=%s latency_ms=%s",
            method,
            path,
            500,
            latency_ms,
        )
        request_metrics.increment(f"{method} {route_label} 500")
        raise

    latency_ms = int((monotonic() - started) * 1000)
    route_label = _metric_route_label(request)
    request_logger.info(
        "request method=%s path=%s status=%s latency_ms=%s",
        method,
        path,
        response.status_code,
        latency_ms,
    )
    key = f"{method} {route_label} {response.status_code}"
    request_metrics.increment(key)
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
    await rate_limiter.close()
    await close_engine()


@app.get("/api/v1", tags=["meta"])
async def api_root() -> dict[str, str]:
    return {
        "name": settings.app_name,
        "version": settings.app_version,
        "status": "ok",
    }


def _build_skill_markdown(base_url: str) -> str:
    docs_url = f"{base_url}/docs"
    register_endpoint = f"{base_url}/api/v1/agents"
    search_endpoint = f"{base_url}/api/v1/agents"
    update_endpoint = f"{base_url}/api/v1/agents/{{agent_id}}"
    delete_endpoint = f"{base_url}/api/v1/agents/{{agent_id}}"

    return (
        dedent(
            f"""\
            ---
            name: agent-agora
            version: {settings.app_version}
            description: Open registry for discovering and registering AI agents via Agent Cards.
            homepage: {base_url}
            ---

            # Agent Agora Skill

            Agent Agora is a public registry where agents can publish Agent Cards and discover other agents.

            ## Authentication (api_key)

            - Registration, update, and deregistration require the `X-API-Key` header.
            - Discovery and `GET /skill.md` are public and do not require authentication.

            ## Register an agent

            **Endpoint:** `POST {register_endpoint}`

            **Required Agent Card fields:**
            - `protocolVersion`
            - `name`
            - `url`
            - `skills` (at least one skill object with `id` and `name`)

            **Example request:**

            ```http
            POST /api/v1/agents
            Content-Type: application/json
            X-API-Key: your-owner-api-key
            ```

            ```json
            {{
              "protocolVersion": "0.3.0",
              "name": "Example Agent",
              "description": "Does useful agent work",
              "url": "https://example.com/agent",
              "version": "1.0.0",
              "skills": [
                {{
                  "id": "example-skill",
                  "name": "Example Skill"
                }}
              ]
            }}
            ```

            **Example response (`201 Created`):**

            ```json
            {{
              "id": "6fca8d4c-2854-4db2-b9eb-d76f053f7490",
              "name": "Example Agent",
              "url": "https://example.com/agent",
              "registered_at": "2026-02-22T18:00:00+00:00",
              "message": "Agent registered successfully"
            }}
            ```

            ## Query the registry

            **Search endpoint:** `GET {search_endpoint}`

            Common query parameters:
            - `q` (keyword search)
            - `skill`
            - `capability`
            - `tag`
            - `health`
            - `limit`, `offset`

            Example:

            ```http
            GET /api/v1/agents?skill=example-skill&limit=20&offset=0
            ```

            ## Update an agent

            **Endpoint:** `PUT {update_endpoint}`

            - Requires `X-API-Key` matching the key used during registration.
            - Agent URL is immutable.

            ## Deregister an agent

            **Endpoint:** `DELETE {delete_endpoint}`

            - Requires `X-API-Key`.
            - Returns `204 No Content` on success.

            ## Full API docs

            - OpenAPI docs: {docs_url}
            """
        ).strip()
        + "\n"
    )


@app.get("/skill.md", response_class=PlainTextResponse, include_in_schema=False)
async def skill_markdown(request: Request) -> PlainTextResponse:
    base_url = str(request.base_url).rstrip("/")
    return PlainTextResponse(_build_skill_markdown(base_url), media_type="text/markdown")


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
                "name": sanitize_ui_text(agent.name, max_length=255),
                "description": sanitize_ui_text(agent.description, max_length=2000),
                "url": sanitize_ui_text(agent.url, max_length=2048),
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
    valid_health_filters = {"healthy", "unhealthy", "unknown"}
    skills = [item.strip() for item in (skill or "").split(",") if item.strip()]
    capabilities = [item.strip() for item in (capability or "").split(",") if item.strip()]
    tags = [item.strip() for item in (tag or "").split(",") if item.strip()]
    health_filters = [health] if health in valid_health_filters else None
    stale_bool: bool | None = None
    if health == "stale":
        stale_bool = True
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
    if stale_bool is True:
        health_filter_ui = "stale"
    elif health_filters:
        health_filter_ui = health_filters[0]
    else:
        health_filter_ui = "all"

    safe_results = {
        **results,
        "agents": [
            {
                **agent,
                "name": sanitize_ui_text(agent["name"], max_length=255),
                "description": sanitize_ui_text(agent.get("description"), max_length=2000),
                "url": sanitize_ui_text(agent["url"], max_length=2048),
            }
            for agent in results["agents"]
        ],
    }

    return templates.TemplateResponse(
        "search.html",
        {
            "request": request,
            "results": safe_results,
            "agents": safe_results["agents"],
            "query": q or "",
            "health_filter": health_filter_ui,
            "sort": request.query_params.get("sort", "recent"),
            "has_more": has_next,
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


@app.get("/agent/{agent_id}", response_class=HTMLResponse, include_in_schema=False)
async def agent_detail_page(
    request: Request,
    agent_id: UUID,
    session: AsyncSession = Depends(get_db_session),
) -> HTMLResponse:
    detail = await get_agent_detail(agent_id=agent_id, session=session)
    safe_agent_card = dict(detail["agent_card"])
    safe_agent_card["name"] = sanitize_ui_text(safe_agent_card.get("name"), max_length=255)
    safe_agent_card["description"] = sanitize_ui_text(
        safe_agent_card.get("description"),
        max_length=2000,
    )
    safe_agent_card["url"] = sanitize_ui_text(safe_agent_card.get("url"), max_length=2048)
    registered_at_raw = detail.get("registered_at")
    registered_at = datetime.fromisoformat(registered_at_raw) if registered_at_raw else None
    last_healthy_at_raw = detail.get("last_healthy_at")
    last_healthy_at = datetime.fromisoformat(last_healthy_at_raw) if last_healthy_at_raw else None

    tenure_days = 0
    if registered_at is not None:
        tenure_days = max(0, (datetime.now(tz=timezone.utc) - registered_at).days)

    agent = {
        "id": detail["id"],
        "name": safe_agent_card.get("name") or "Unnamed agent",
        "description": safe_agent_card.get("description"),
        "url": safe_agent_card.get("url"),
        "health_status": detail.get("health_status") or "unknown",
        "is_verified": False,
        "tenure_days": tenure_days,
        "protocol_version": safe_agent_card.get("protocolVersion"),
        "created_at": registered_at,
        "last_healthy_at": last_healthy_at,
        "version": safe_agent_card.get("version"),
        "skills": safe_agent_card.get("skills") or [],
        "card": safe_agent_card,
    }

    return templates.TemplateResponse(
        "agent_detail.html",
        {
            "request": request,
            "agent": agent,
            "health_history": [],
            "is_owner": False,
        },
    )


@app.get("/register", response_class=HTMLResponse, include_in_schema=False)
async def register_page(request: Request) -> HTMLResponse:
    registry_base_url = str(request.base_url).rstrip("/")
    register_endpoint = f"{registry_base_url}/api/v1/agents"
    health_endpoint = f"{registry_base_url}/api/v1/health"
    skill_url = "https://github.com/archedark-publishing/agora/blob/main/.agents/skills/agora-agent-registry/SKILL.md"
    handoff_prompt = f"""Register me on the Agora — an open registry for A2A agent discovery.

**Registry:** {registry_base_url}
**Full guide:** {skill_url}

## Instructions

1. Read the SKILL.md at {skill_url} for the complete registration flow and agent card schema.

2. Generate a secure owner API key (e.g., `openssl rand -hex 16`). Store it in your credential manager (1Password, etc.) — you'll need it for future updates. Do not commit it to git or expose in logs.

3. Build an Agent Card JSON with these required fields:
   - protocolVersion: "0.3.0"
   - name: Your agent's display name
   - url: Your canonical public URL
   - skills: Array of capabilities (each needs id and name)

4. Register via POST {register_endpoint}
   - Header: X-API-Key: <your-owner-key>
   - Body: Your agent card JSON

5. Verify registration succeeded and report the agent ID.

If anything fails, check the error response and SKILL.md troubleshooting section."""
    return templates.TemplateResponse(
        "register.html",
        {
            "request": request,
            "registry_base_url": registry_base_url,
            "register_endpoint": register_endpoint,
            "health_endpoint": health_endpoint,
            "handoff_prompt": handoff_prompt,
        },
    )


@app.get("/recover", response_class=HTMLResponse, include_in_schema=False)
async def recover_page(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(
        "recover.html",
        {
            "request": request,
            "start_error": None,
            "complete_error": None,
            "start_result": None,
            "complete_result": None,
            "agent_id_value": "",
            "recovery_session_secret_value": "",
        },
    )


@app.post("/recover/start", response_class=HTMLResponse, include_in_schema=False)
async def recover_start_page(
    request: Request,
    session: AsyncSession = Depends(get_db_session),
    agent_id: str = Form(...),
) -> HTMLResponse:
    try:
        parsed_id = UUID(agent_id)
    except ValueError:
        return templates.TemplateResponse(
            "recover.html",
            {
                "request": request,
                "start_error": "Invalid agent ID format",
                "complete_error": None,
                "start_result": None,
                "complete_result": None,
                "agent_id_value": agent_id,
                "recovery_session_secret_value": "",
            },
            status_code=400,
        )

    try:
        result = await start_recovery(agent_id=parsed_id, request=request, session=session)
    except HTTPException as exc:
        return templates.TemplateResponse(
            "recover.html",
            {
                "request": request,
                "start_error": exc.detail,
                "complete_error": None,
                "start_result": None,
                "complete_result": None,
                "agent_id_value": agent_id,
                "recovery_session_secret_value": "",
            },
            status_code=exc.status_code,
        )

    return templates.TemplateResponse(
        "recover.html",
        {
            "request": request,
            "start_error": None,
            "complete_error": None,
            "start_result": result,
            "complete_result": None,
            "agent_id_value": agent_id,
            "recovery_session_secret_value": result["recovery_session_secret"],
        },
        status_code=200,
    )


@app.post("/recover/complete", response_class=HTMLResponse, include_in_schema=False)
async def recover_complete_page(
    request: Request,
    session: AsyncSession = Depends(get_db_session),
    agent_id: str = Form(...),
    new_api_key: str = Form(...),
    recovery_session_secret: str = Form(...),
) -> HTMLResponse:
    try:
        parsed_id = UUID(agent_id)
    except ValueError:
        return templates.TemplateResponse(
            "recover.html",
            {
                "request": request,
                "start_error": None,
                "complete_error": "Invalid agent ID format",
                "start_result": None,
                "complete_result": None,
                "agent_id_value": agent_id,
                "recovery_session_secret_value": recovery_session_secret,
            },
            status_code=400,
        )

    try:
        result = await complete_recovery(
            agent_id=parsed_id,
            request=request,
            session=session,
            api_key=new_api_key,
            recovery_session_secret=recovery_session_secret,
        )
    except HTTPException as exc:
        return templates.TemplateResponse(
            "recover.html",
            {
                "request": request,
                "start_error": None,
                "complete_error": exc.detail,
                "start_result": None,
                "complete_result": None,
                "agent_id_value": agent_id,
                "recovery_session_secret_value": recovery_session_secret,
            },
            status_code=exc.status_code,
        )

    return templates.TemplateResponse(
        "recover.html",
        {
            "request": request,
            "start_error": None,
            "complete_error": None,
            "start_result": None,
            "complete_result": result,
            "agent_id_value": agent_id,
            "recovery_session_secret_value": "",
        },
        status_code=200,
    )


def _build_verify_url(agent_url: str) -> str:
    """Return the recovery verification URL for an agent origin."""

    parts = urlsplit(agent_url)
    host = parts.hostname or ""
    port = parts.port
    if port and port != 443:
        return f"https://{host}:{port}/.well-known/agora-verify"
    return f"https://{host}/.well-known/agora-verify"


def _invalid_agent_card_length_detail() -> dict[str, Any]:
    return {
        "message": "Invalid Agent Card",
        "errors": [
            {
                "field": "agent_card",
                "message": "One or more fields exceed maximum allowed length",
                "type": "value_error.any_str.max_length",
            }
        ],
    }


async def _fetch_recovery_token(
    verify_url: str,
    *,
    pinned_hostname: str,
    pinned_ip: ipaddress.IPv4Address | ipaddress.IPv6Address,
) -> str:
    timeout = httpx.Timeout(settings.outbound_http_timeout_seconds)
    async with pin_hostname_resolution(pinned_hostname, pinned_ip):
        async with httpx.AsyncClient(timeout=timeout, follow_redirects=False) as client:
            response = await client.get(verify_url)
            response.raise_for_status()
            return response.text


def _client_ip(request: Request) -> str:
    return request.client.host if request.client else "unknown"


async def _enforce_rate_limit(
    *,
    key: str,
    limit: int,
    window_seconds: int = RATE_LIMIT_WINDOW_SECONDS,
) -> None:
    try:
        result = await rate_limiter.check(key=key, limit=limit, window_seconds=window_seconds)
    except RateLimitBackendError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Rate limiting unavailable",
        ) from exc
    if result.allowed:
        return
    raise HTTPException(
        status_code=status.HTTP_429_TOO_MANY_REQUESTS,
        detail="Rate limit exceeded",
        headers={"Retry-After": str(result.retry_after_seconds)},
    )


async def _enforce_registration_rate_limits(request: Request, api_key: str) -> None:
    ip = _client_ip(request)
    await _enforce_rate_limit(
        key=f"api:post_agents:ip:{ip}",
        limit=settings.registration_rate_limit_per_ip,
    )
    await _enforce_rate_limit(
        key=f"api:post_agents:key:{api_key_fingerprint(api_key)}",
        limit=settings.registration_rate_limit_per_api_key,
    )
    await _enforce_rate_limit(
        key="api:post_agents:global",
        limit=settings.registration_rate_limit_global,
    )


async def _enforce_list_agents_rate_limits(request: Request, api_key: str | None) -> None:
    ip = _client_ip(request)
    await _enforce_rate_limit(
        key=f"api:get_agents:ip:{ip}",
        limit=settings.list_agents_rate_limit_per_ip,
    )
    if api_key:
        await _enforce_rate_limit(
            key=f"api:get_agents:key:{api_key_fingerprint(api_key)}",
            limit=settings.list_agents_rate_limit_per_api_key,
        )
    await _enforce_rate_limit(
        key="api:get_agents:global",
        limit=settings.list_agents_rate_limit_global,
    )


async def _enforce_admin_rate_limits(request: Request, *, scope: str) -> None:
    ip = _client_ip(request)
    await _enforce_rate_limit(
        key=f"api:admin:{scope}:ip:{ip}",
        limit=settings.admin_rate_limit_per_ip,
    )
    await _enforce_rate_limit(
        key=f"api:admin:{scope}:global",
        limit=settings.admin_rate_limit_global,
    )


async def _enforce_recovery_rate_limits(request: Request, agent_id: UUID, action: str) -> None:
    ip = _client_ip(request)
    if action == "start":
        ip_limit = 5
        agent_limit = 3
    else:
        ip_limit = 10
        agent_limit = 5

    try:
        await _enforce_rate_limit(
            key=f"recovery:{action}:ip:{ip}",
            limit=ip_limit,
            window_seconds=RATE_LIMIT_WINDOW_SECONDS,
        )
    except HTTPException as exc:
        if exc.status_code != status.HTTP_429_TOO_MANY_REQUESTS:
            raise
        recovery_logger.warning(
            "recovery_abuse action=%s agent_id=%s source_ip=%s outcome=rate_limited_ip retry_after=%s",
            action,
            agent_id,
            ip,
            (exc.headers or {}).get("Retry-After", "1"),
        )
        raise

    try:
        await _enforce_rate_limit(
            key=f"recovery:{action}:agent:{agent_id}",
            limit=agent_limit,
            window_seconds=RATE_LIMIT_WINDOW_SECONDS,
        )
    except HTTPException as exc:
        if exc.status_code != status.HTTP_429_TOO_MANY_REQUESTS:
            raise
        recovery_logger.warning(
            "recovery_abuse action=%s agent_id=%s source_ip=%s outcome=rate_limited_agent retry_after=%s",
            action,
            agent_id,
            ip,
            (exc.headers or {}).get("Retry-After", "1"),
        )
        raise


def _upgrade_owner_key_hash_if_needed(agent: Agent, api_key: str) -> bool:
    if not should_rehash_api_key_hash(agent.owner_key_hash):
        return False
    agent.owner_key_hash = hash_api_key(api_key)
    return True


@app.post("/api/v1/agents", status_code=status.HTTP_201_CREATED, tags=["agents"])
async def register_agent(
    agent_card_payload: dict[str, Any],
    request: Request,
    session: AsyncSession = Depends(get_db_session),
    api_key: str = Header(alias="X-API-Key", min_length=1),
) -> dict[str, str]:
    await _enforce_registration_rate_limits(request, api_key)

    sanitized_payload = sanitize_json_strings(agent_card_payload)
    try:
        validated = validate_agent_card(sanitized_payload)
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
            allow_unresolvable=settings.allow_unresolvable_registration_hostnames,
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
    except (DataError, DBAPIError) as exc:
        await session.rollback()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=_invalid_agent_card_length_detail(),
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
    await _enforce_recovery_rate_limits(request, agent_id, action="start")
    agent = await session.get(Agent, agent_id)
    if agent is None:
        recovery_logger.info(
            "recovery_abuse action=start agent_id=%s source_ip=%s outcome=not_found",
            agent_id,
            _client_ip(request),
        )
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Agent not found")

    challenge_token = token_urlsafe(32)
    recovery_session_secret = token_urlsafe(32)
    now_utc = datetime.now(tz=timezone.utc)
    expires_at = now_utc + timedelta(seconds=settings.recovery_challenge_ttl_seconds)

    # Enforces single active challenge by replacing the prior hash/metadata.
    agent.recovery_challenge_hash = hash_api_key(challenge_token)
    agent.recovery_session_hash = api_key_fingerprint(recovery_session_secret)
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
        "recovery_session_secret": recovery_session_secret,
        "verify_url": _build_verify_url(agent.url),
        "expires_at": expires_at.isoformat(),
    }


@app.post("/api/v1/agents/{agent_id}/recovery/complete", tags=["recovery"])
async def complete_recovery(
    agent_id: UUID,
    request: Request,
    session: AsyncSession = Depends(get_db_session),
    api_key: str = Header(alias="X-API-Key", min_length=1),
    recovery_session_secret: str = Header(alias="X-Recovery-Session", min_length=1),
) -> dict[str, str]:
    await _enforce_recovery_rate_limits(request, agent_id, action="complete")
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
        or agent.recovery_session_hash is None
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
        safe_target = assert_url_safe_for_outbound(
            verify_url,
            allow_private=settings.allow_private_network_targets,
        )
        fetched_token = await _fetch_recovery_token(
            verify_url,
            pinned_hostname=safe_target.hostname,
            pinned_ip=safe_target.pinned_ip,
        )
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

    provided_session_hash = api_key_fingerprint(recovery_session_secret)
    if not hmac.compare_digest(provided_session_hash, agent.recovery_session_hash):
        recovery_logger.info(
            "recovery_abuse action=complete agent_id=%s source_ip=%s outcome=session_mismatch",
            agent_id,
            _client_ip(request),
        )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Recovery session mismatch",
        )

    expected_challenge_hash = agent.recovery_challenge_hash
    expected_session_hash = agent.recovery_session_hash
    update_result = await session.execute(
        update(Agent)
        .where(
            Agent.id == agent_id,
            Agent.recovery_challenge_hash == expected_challenge_hash,
            Agent.recovery_session_hash == expected_session_hash,
            Agent.recovery_challenge_expires_at.is_not(None),
            Agent.recovery_challenge_expires_at > now_utc,
        )
        .values(
            owner_key_hash=hash_api_key(api_key),
            recovery_challenge_hash=None,
            recovery_session_hash=None,
            recovery_challenge_created_at=None,
            recovery_challenge_expires_at=None,
        )
    )
    if update_result.rowcount != 1:
        await session.rollback()
        recovery_logger.info(
            "recovery_abuse action=complete agent_id=%s source_ip=%s outcome=challenge_consumed",
            agent_id,
            _client_ip(request),
        )
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Recovery challenge already consumed",
        )

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
    await _enforce_rate_limit(
        key=f"api:put_agent:key:{api_key_fingerprint(api_key)}",
        limit=20,
    )

    agent = await session.get(Agent, agent_id)
    if agent is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Agent not found")

    if not verify_api_key(api_key, agent.owner_key_hash):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid API key")
    _upgrade_owner_key_hash_if_needed(agent, api_key)

    sanitized_payload = sanitize_json_strings(agent_card_payload)
    try:
        validated = validate_agent_card(sanitized_payload)
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
            allow_unresolvable=settings.allow_unresolvable_registration_hostnames,
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
    try:
        await session.commit()
    except (DataError, DBAPIError) as exc:
        await session.rollback()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=_invalid_agent_card_length_detail(),
        ) from exc
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
    await _enforce_list_agents_rate_limits(request, api_key)

    filters: list[Any] = []
    if skill:
        filters.append(Agent.skills.overlap(skill))
    if capability:
        filters.append(Agent.capabilities.overlap(capability))
    if tag:
        filters.append(Agent.tags.overlap(tag))

    effective_stale = stale
    if health:
        health_values = [value for value in health if value not in {"all", "stale"}]
        if "stale" in health and effective_stale is None:
            effective_stale = True

        allowed_health_values = {"healthy", "unhealthy", "unknown"}
        invalid_values = [value for value in health_values if value not in allowed_health_values]
        if invalid_values:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid health value(s): {', '.join(invalid_values)}",
            )
        if health_values:
            filters.append(Agent.health_status.in_(health_values))

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
    if effective_stale is True:
        filters.append(stale_expr)
    elif effective_stale is False:
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
    request: Request,
    session: AsyncSession = Depends(get_db_session),
    admin_token: str | None = Header(default=None, alias="X-Admin-Token"),
) -> dict[str, Any]:
    await _require_admin_token(request, admin_token, scope="stale-candidates")

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
    await _enforce_rate_limit(
        key=f"api:delete_agent:key:{api_key_fingerprint(api_key)}",
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
    await _enforce_rate_limit(
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
async def metrics(
    request: Request,
    admin_token: str | None = Header(default=None, alias="X-Admin-Token"),
) -> dict[str, Any]:
    await _require_admin_token(request, admin_token, scope="metrics")
    return {
        "request_metrics": request_metrics.snapshot(),
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
