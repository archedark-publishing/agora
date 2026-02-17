# Operations Guide

## Environment Variables

Copy `.env.example` to `.env` and adjust as needed.

| Variable | Default | Purpose |
|---|---|---|
| `APP_NAME` | `Agora` | API display name |
| `APP_VERSION` | `0.1.0` | API version string |
| `ENVIRONMENT` | `development` | Runtime environment label |
| `LOG_LEVEL` | `INFO` | Python logging verbosity |
| `DATABASE_URL` | `postgresql+asyncpg://agora:password@localhost:5432/agora` | Postgres DSN |
| `DATABASE_ECHO_SQL` | `false` | Enable SQLAlchemy SQL/params echo logging |
| `MAX_REQUEST_BODY_BYTES` | `1048576` | Reject requests larger than this many bytes (via `Content-Length`) |
| `HEALTH_CHECK_INTERVAL` | `3600` | Seconds between health-check cycles |
| `RECOVERY_CHALLENGE_TTL_SECONDS` | `900` | Recovery challenge TTL |
| `OUTBOUND_HTTP_TIMEOUT_SECONDS` | `10` | Timeout for outbound HTTP checks |
| `REGISTRY_REFRESH_INTERVAL` | `3600` | Seconds between `registry.json` refreshes |
| `ADMIN_API_TOKEN` | empty | Required for admin/metrics endpoints |
| `ALLOW_PRIVATE_NETWORK_TARGETS` | `false` | Dev/testing override for private host checks |
| `ALLOW_UNRESOLVABLE_REGISTRATION_HOSTNAMES` | `false` | Dev/testing override to allow unresolved registration hostnames |
| `RATE_LIMIT_BACKEND` | `auto` | `auto`, `memory`, or `redis` |
| `REDIS_URL` | empty | Redis URL for shared rate limiting |
| `RATE_LIMIT_PREFIX` | `agora:rate_limit` | Redis key namespace prefix |
| `REGISTRATION_RATE_LIMIT_PER_IP` | `10` | `POST /api/v1/agents` per-source-IP limit |
| `REGISTRATION_RATE_LIMIT_PER_API_KEY` | `10` | `POST /api/v1/agents` per-key secondary limit |
| `REGISTRATION_RATE_LIMIT_GLOBAL` | `200` | `POST /api/v1/agents` global limit |
| `LIST_AGENTS_RATE_LIMIT_PER_IP` | `100` | `GET /api/v1/agents` per-source-IP limit (always applied) |
| `LIST_AGENTS_RATE_LIMIT_PER_API_KEY` | `1000` | `GET /api/v1/agents` additional per-key secondary limit |
| `LIST_AGENTS_RATE_LIMIT_GLOBAL` | `5000` | `GET /api/v1/agents` global limit |
| `ADMIN_RATE_LIMIT_PER_IP` | `30` | Per-IP limit for admin token endpoints |
| `ADMIN_RATE_LIMIT_GLOBAL` | `300` | Global limit for admin token endpoints |
| `METRICS_MAX_ENTRIES` | `2048` | Max in-memory metric key cardinality |
| `MONTHLY_BUDGET_CENTS` | empty | Reserved budget setting |

## Background Jobs

- Health checker:
  - Runs every `HEALTH_CHECK_INTERVAL`.
  - Checks only agents queried in the last 24 hours.
  - Probes `/.well-known/agent-card.json` on each agent origin.
  - Updates `health_status`, `last_health_check`, and `last_healthy_at`.
  - Does not delete stale agents.

- Registry refresher:
  - Runs every `REGISTRY_REFRESH_INTERVAL`.
  - Rebuilds cached snapshot for `/api/v1/registry.json`.

## Stale Semantics

- Stale threshold: 7 days.
- An agent is stale only when `health_status == unhealthy` and:
  - `last_healthy_at` is older than 7 days, or
  - never healthy and `registered_at` is older than 7 days.
- `unknown` agents are never stale.
- Staleness is advisory only in MVP; no auto-removal is performed.

## Rate Limits

Window: 1 hour.

| Endpoint | Limit |
|---|---|
| `POST /api/v1/agents` | 10/hour per source IP + 10/hour per API key + 200/hour global |
| `GET /api/v1/agents` | 100/hour per source IP + 1000/hour per API key + 5000/hour global |
| `PUT /api/v1/agents/{id}` | 20/hour per API key |
| `DELETE /api/v1/agents/{id}` | 10/hour per API key |
| `GET /api/v1/registry.json` | 10/hour per IP |
| `POST /api/v1/agents/{id}/recovery/start` | 5/hour per IP and 3/hour per agent |
| `POST /api/v1/agents/{id}/recovery/complete` | 10/hour per IP and 5/hour per agent |
| `GET /api/v1/metrics` + `GET /api/v1/admin/stale-candidates` | 30/hour per source IP + 300/hour global |

Rate-limited responses return `429` and `Retry-After`.

For multi-instance deployments, configure `RATE_LIMIT_BACKEND=redis` + `REDIS_URL`.

## SSRF and URL Safety

- Registration/update reject private/internal/localhost targets by default.
- Registration also rejects unresolved hostnames by default.
- Recovery and health outbound probes enforce safe public targets by default and pin DNS resolution for each request to prevent rebinding between check and connect.
- For isolated dev environments, set `ALLOW_PRIVATE_NETWORK_TARGETS=true`.
- To allow unresolved hostnames in non-production experiments, set `ALLOW_UNRESOLVABLE_REGISTRATION_HOSTNAMES=true`.

## Observability

- Request logs include method, path, status, and latency.
- Recovery abuse logs include source IP, agent ID, and outcome.
- Metrics endpoint: `GET /api/v1/metrics` (requires `X-Admin-Token` and uses bounded route-template counters).

## Registry Export Behavior

`GET /api/v1/registry.json` returns cached snapshot with:

- `Cache-Control: public, max-age=300, stale-while-revalidate=120`
- `ETag`
- `Last-Modified`
