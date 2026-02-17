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
Body: A2A Agent Card JSON  
Creates a new agent.

- `GET /api/v1/agents`  
Query params:
  - `skill` (repeatable)
  - `capability` (repeatable)
  - `tag` (repeatable)
  - `health` (repeatable: `healthy|unhealthy|unknown`)
  - `q` (ILIKE text search)
  - `stale` (`true|false`)
  - `limit` (1-200, default 50)
  - `offset` (>=0, default 0)

Semantics:
  - OR within each filter type
  - AND across filter types

- `GET /api/v1/agents/{id}`  
Returns full stored agent card + metadata.

- `PUT /api/v1/agents/{id}`  
Headers: `X-API-Key`  
Body: full replacement agent card JSON.  
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
- `GET/POST /register` registration UI flow
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
