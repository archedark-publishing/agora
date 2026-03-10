# API Reference (MVP)

Base URL examples use `http://localhost:8000`.

## Meta + Health

- `GET /api/v1`  
Returns service name/version/status.

- `GET /api/v1/health`  
Basic service + DB health with uptime and agent count.

- `GET /api/v1/health/db`  
Explicit DB probe (`503` if DB is unavailable).

## Agents

- `POST /api/v1/agents`  
Headers: `X-API-Key`  
Body: A2A Agent Card JSON plus optional `econ_id` string (for ERC-8004 use `{agentRegistry}:{agentId}`, e.g. `eip155:1:0x742...:22`) and optional `protocol_version` string (nullable, max 32; exact value is not validated).  
Creates a new agent. During registration Agora attempts to fetch `https://{endpoint-domain}/.well-known/agent-registration.json`; if valid, it auto-populates/verifies `econ_id` and sets `erc8004_verified`.

- `GET /api/v1/agents`  
Query params:
  - `skill` (repeatable)
  - `capability` (repeatable)
  - `tag` (repeatable)
  - `health` (repeatable: `healthy|unhealthy|unknown`)
  - `q` (ILIKE text search)
  - `stale` (`true|false`)
  - `has_econ_id` (`true|false`)
  - `econ_id` (exact string match)
  - `has_protocol_version` (`true|false`)
  - `protocol_version` (exact string match)
  - `limit` (1-200, default 50)
  - `offset` (>=0, default 0)

Semantics:
  - OR within each filter type
  - AND across filter types

List responses include `protocol_version`, `econ_id`, and `erc8004_verified` for each agent row.

- `GET /api/v1/agents/{id}`  
Returns full stored agent card + metadata, including `protocol_version` (or `null`), `econ_id` (or `null`), and `erc8004_verified` (`true|false`).

- `GET /api/v1/me`  
Headers: `X-API-Key`  
Returns the same payload shape as `GET /api/v1/agents/{id}` for the authenticated agent (self-view).

- `PUT /api/v1/agents/{id}`  
Headers: `X-API-Key`  
Body: full replacement agent card JSON; optional `econ_id` and `protocol_version` may be set/updated/cleared.  
URL is immutable and must match stored normalized URL.

- `DELETE /api/v1/agents/{id}`  
Headers: `X-API-Key`  
Deletes the agent on valid key.

## Recovery

- `POST /api/v1/agents/{id}/recovery/start`  
No key required.  
Returns one-time challenge token, recovery session secret, verify URL, and expiration timestamp.

- `POST /api/v1/agents/{id}/recovery/complete`  
Headers: `X-API-Key` (new owner key), `X-Recovery-Session` (from recovery start)  
Fetches verification token from `https://<agent-origin>/.well-known/agora-verify`, verifies, rotates key.

## Registry + Observability

- `GET /api/v1/registry.json`  
Serves the latest cached registry snapshot with cache headers.

- `GET /api/v1/metrics`  
Headers: `X-Admin-Token`  
Returns bounded in-memory request metrics and last health summary when `ADMIN_API_TOKEN` is configured.

- `GET /api/v1/admin/stale-candidates`  
Headers: `X-Admin-Token`  
Returns stale candidates report if `ADMIN_API_TOKEN` is configured.

## Web Routes

- `GET /` home
- `GET /search` search UI
- `GET /agent/{id}` detail UI
- `GET /register` agent handoff packet UI (for agent-driven registration)
- `GET/POST /recover` recovery UI flow

## Status Codes (Common)

- `200` success
- `201` created
- `204` deleted
- `400` validation/input/recovery mismatch
- `401` invalid API/admin key
- `404` unknown resource
- `409` duplicate normalized URL
- `413` payload too large
- `429` rate limit exceeded (includes `Retry-After`)
