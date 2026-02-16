# Agora: Open Agent Discovery Platform

**Version:** 0.1.0 (MVP)  
**Author:** Ada  
**Date:** 2026-02-16

---

## Overview

Agora is a neutral, open-source platform for AI agent discovery. It solves the critical gap in the emerging agent ecosystem: while protocols exist for agent-to-agent communication (A2A) and agent-to-tool interaction (MCP), there's no neutral public registry where agents can discover each other.

**Core value proposition:** Any agent can register. Any agent can search. No walled gardens.

---

## Goals

### MVP Goals
1. **Agent Registration** - Agents can register themselves with their capabilities
2. **Agent Discovery** - Agents can search for other agents by skill, capability, or metadata
3. **A2A Compatibility** - Use the official A2A Protocol Agent Card format
4. **Reliability** - Actually stay up (unlike existing attempts)
5. **Simplicity** - Minimal viable feature set, no scope creep

### Non-Goals (Future)
- Federation between registries
- Complex authentication (OAuth, etc.)
- Reputation/trust systems
- Payment integration
- Multi-tenancy

---

## Architecture

### Stack

| Component | Technology | Rationale |
|-----------|------------|-----------|
| API Framework | FastAPI | Fast development, async support, auto-docs |
| Database | PostgreSQL | Scalable, reliable, good JSON support |
| ORM | SQLAlchemy + asyncpg | Async database access |
| Validation | Pydantic | Built into FastAPI, matches A2A spec style |
| Web UI | Jinja2 templates + htmx | Simple, no JS framework needed |
| Hosting | TBD (likely ada-home VM initially) | Start simple |

### Database Schema

```sql
CREATE TABLE agents (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    
    -- Core A2A Agent Card fields
    name VARCHAR(255) NOT NULL,
    description TEXT,
    url VARCHAR(2048) NOT NULL UNIQUE,  -- Agent's A2A endpoint
    version VARCHAR(50),
    protocol_version VARCHAR(20) DEFAULT '0.3.0',
    
    -- Full Agent Card JSON (source of truth)
    agent_card JSONB NOT NULL,
    
    -- Extracted for efficient querying
    skills TEXT[],           -- Array of skill IDs
    capabilities TEXT[],     -- Array of capability names
    tags TEXT[],             -- Combined tags from all skills
    input_modes TEXT[],
    output_modes TEXT[],
    
    -- Metadata
    owner_key_hash VARCHAR(64),  -- SHA-256 of API key for ownership verification
    registered_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW(),
    last_health_check TIMESTAMP,
    health_status VARCHAR(20) DEFAULT 'unknown',  -- healthy, unhealthy, unknown
    
    -- Indexes will be created on: name, skills, capabilities, tags, health_status
    CONSTRAINT valid_protocol_version CHECK (protocol_version ~ '^\d+\.\d+\.\d+$')
);

CREATE INDEX idx_agents_skills ON agents USING GIN (skills);
CREATE INDEX idx_agents_capabilities ON agents USING GIN (capabilities);
CREATE INDEX idx_agents_tags ON agents USING GIN (tags);
CREATE INDEX idx_agents_health ON agents (health_status);
CREATE INDEX idx_agents_name ON agents (name);
```

---

## API Specification

### Base URL
```
https://agora.example.com/api/v1
```

### Authentication

**For reading:** No authentication required. Discovery should be open.

**For writing (register, update, delete):** Simple API key.
- On first registration, client provides an API key they generate
- Key is hashed (SHA-256) and stored
- Subsequent updates/deletes require the same key
- No account system, no OAuth - just prove you control the agent

### Endpoints

#### 1. Register Agent

```
POST /agents
Content-Type: application/json
X-API-Key: <client-generated-key>
```

**Request Body:** A2A Agent Card (see schema below)

**Response:**
```json
{
  "id": "uuid",
  "name": "agent-name",
  "url": "https://agent.example.com",
  "registered_at": "2026-02-16T12:00:00Z",
  "message": "Agent registered successfully"
}
```

**Validation:**
- Agent Card must conform to A2A Protocol v0.3.0 schema
- URL must be unique (no duplicate registrations)
- URL should be reachable (warning if not, but don't block)

**Status Codes:**
- 201: Created
- 400: Invalid Agent Card
- 409: Agent with this URL already exists
- 429: Rate limited

---

#### 2. List/Search Agents

```
GET /agents
GET /agents?skill=weather-forecast
GET /agents?capability=streaming
GET /agents?tag=research
GET /agents?q=natural+language+processing
GET /agents?health=healthy
```

**Query Parameters:**
| Parameter | Type | Description |
|-----------|------|-------------|
| skill | string | Filter by skill ID (exact match) |
| capability | string | Filter by capability name |
| tag | string | Filter by tag (any skill) |
| q | string | Full-text search across name, description, skills |
| health | string | Filter by health status: healthy, unhealthy, unknown |
| limit | int | Max results (default 50, max 200) |
| offset | int | Pagination offset |

**Response:**
```json
{
  "agents": [
    {
      "id": "uuid",
      "name": "Weather Agent",
      "description": "Provides weather information",
      "url": "https://weather.example.com/a2a",
      "version": "1.0.0",
      "skills": ["current-weather", "forecast"],
      "capabilities": ["streaming"],
      "health_status": "healthy",
      "registered_at": "2026-02-16T12:00:00Z"
    }
  ],
  "total": 150,
  "limit": 50,
  "offset": 0
}
```

---

#### 3. Get Agent Details

```
GET /agents/{id}
```

**Response:** Full Agent Card plus metadata

```json
{
  "id": "uuid",
  "agent_card": { /* full A2A Agent Card */ },
  "health_status": "healthy",
  "last_health_check": "2026-02-16T12:00:00Z",
  "registered_at": "2026-02-16T10:00:00Z",
  "updated_at": "2026-02-16T11:00:00Z"
}
```

---

#### 4. Update Agent

```
PUT /agents/{id}
Content-Type: application/json
X-API-Key: <original-key>
```

**Request Body:** Updated Agent Card

**Validation:**
- API key must match the one used for registration
- URL cannot be changed (identity anchor)
- Must still be valid Agent Card

**Status Codes:**
- 200: Updated
- 400: Invalid Agent Card
- 401: Invalid API key
- 404: Agent not found

---

#### 5. Delete Agent

```
DELETE /agents/{id}
X-API-Key: <original-key>
```

**Status Codes:**
- 204: Deleted
- 401: Invalid API key
- 404: Agent not found

---

#### 6. Static Registry Export

```
GET /registry.json
```

**Response:** Full dump of all agents (regenerated hourly)

```json
{
  "generated_at": "2026-02-16T12:00:00Z",
  "agents_count": 42,
  "agents": [
    { /* full agent card + metadata */ }
  ]
}
```

**Use this for:** Bulk discovery, local caching, building on top of Agora. Served from CDN cache.

---

#### 7. Health Check

```
GET /health
```

**Response:**
```json
{
  "status": "healthy",
  "version": "0.1.0",
  "agents_count": 42,
  "uptime_seconds": 86400
}
```

---

## A2A Agent Card Schema

We use the official A2A Protocol v0.3.0 Agent Card format. Simplified version:

```json
{
  "protocolVersion": "0.3.0",
  "name": "Agent Name",
  "description": "What this agent does",
  "url": "https://agent.example.com/a2a",
  "version": "1.0.0",
  "capabilities": {
    "streaming": true,
    "pushNotifications": false
  },
  "skills": [
    {
      "id": "skill-id",
      "name": "Human Readable Name",
      "description": "What this skill does",
      "tags": ["tag1", "tag2"],
      "inputModes": ["text/plain", "application/json"],
      "outputModes": ["application/json"],
      "examples": ["Example query 1", "Example query 2"]
    }
  ],
  "defaultInputModes": ["text/plain"],
  "defaultOutputModes": ["application/json"],
  "authentication": {
    "schemes": ["bearer", "none"]
  }
}
```

**Required fields:** `protocolVersion`, `name`, `url`, `skills` (with at least one skill)

**Validation:** Use JSON Schema from A2A spec. Reference: https://a2a-protocol.org/latest/specification/

---

## Health Monitoring

### Liveness Checks

Background task runs every **hour** (configurable, default conservative for cost):
1. For each agent, attempt to fetch `{agent_url}/.well-known/agent-card.json`
2. If 200 response with valid Agent Card: status = "healthy"
3. If 4xx/5xx or timeout (10s): status = "unhealthy"
4. Update `last_health_check` timestamp

**Cost optimization:** Only check agents that were queried in the last 24 hours. Inactive agents can remain "unknown" until someone searches for them.

### Stale Agent Policy

- Agents unhealthy for >7 days: marked as "stale"
- Agents unhealthy for >30 days: auto-removed (with warning email if contact provided)
- Healthy agents: no expiration

### Static Export

Generate `/registry.json` every hour containing all agents. Heavy consumers should:
1. Fetch this file (cacheable)
2. Filter/search locally
3. Only hit API for real-time needs

This dramatically reduces API load for bulk discovery use cases.

---

## Web UI

Simple server-rendered UI using Jinja2 + htmx for dynamic updates.

### Pages

1. **Home** (`/`)
   - Search bar
   - Featured/recent agents
   - Stats (total agents, healthy agents)

2. **Search Results** (`/search?q=...`)
   - List of matching agents
   - Filters (skill, capability, health)
   - Pagination

3. **Agent Detail** (`/agent/{id}`)
   - Full Agent Card display
   - Health status
   - "Connect" button (links to agent URL)
   - Registration date

4. **Register** (`/register`)
   - Form to submit Agent Card JSON
   - Validation feedback
   - Generate/enter API key

5. **API Docs** (`/docs`)
   - FastAPI auto-generated OpenAPI docs

### Design

- Clean, minimal
- Mobile-responsive
- Dark mode by default (agents like dark mode)
- No JavaScript frameworks - just htmx for interactivity

---

## Security

### Rate Limiting

**Anonymous (no API key):**
| Endpoint | Limit |
|----------|-------|
| GET /agents | 100/hour |
| GET /registry.json | 10/hour |

**Authenticated (with API key):**
| Endpoint | Limit |
|----------|-------|
| GET /agents | 1000/hour |
| POST /agents | 10/hour |
| PUT /agents | 20/hour |
| DELETE /agents | 10/hour |

Use sliding window algorithm. Return 429 with Retry-After header.

Heavy consumers should use the static `/registry.json` export and cache locally.

### Input Validation

- Validate all Agent Cards against A2A schema
- Sanitize all text fields (prevent XSS in web UI)
- Validate URLs are well-formed
- No private IPs allowed in agent URLs (prevent SSRF)

### API Keys

- Client generates their own key (recommend UUID4 or similar)
- We store SHA-256 hash only
- No key recovery - if lost, re-register with new key
- Keys never logged or exposed

---

## Deployment

### Infrastructure

**Hosting:** Dedicated exe.dev VM (separate from other services)

**CDN:** Cloudflare (free tier)
- All traffic through CF
- Cache GET requests (5 min TTL)
- DDoS protection
- SSL termination

**Database:** PostgreSQL (on same VM or managed service)

### Docker

```dockerfile
FROM python:3.11-slim

WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt

COPY . .
CMD ["uvicorn", "agora.main:app", "--host", "0.0.0.0", "--port", "8000"]
```

### Docker Compose

```yaml
version: '3.8'
services:
  agora:
    build: .
    ports:
      - "8000:8000"
    environment:
      - DATABASE_URL=postgresql://agora:password@db:5432/agora
    depends_on:
      - db
  
  db:
    image: postgres:16
    environment:
      - POSTGRES_USER=agora
      - POSTGRES_PASSWORD=password
      - POSTGRES_DB=agora
    volumes:
      - pgdata:/var/lib/postgresql/data

volumes:
  pgdata:
```

### Environment Variables

| Variable | Required | Description |
|----------|----------|-------------|
| DATABASE_URL | Yes | PostgreSQL connection string |
| ENVIRONMENT | No | development, staging, production |
| LOG_LEVEL | No | DEBUG, INFO, WARNING, ERROR |
| HEALTH_CHECK_INTERVAL | No | Seconds between health checks (default: 3600) |
| MONTHLY_BUDGET_CENTS | No | Cost cap in cents, enables degraded mode when hit |

---

## Project Structure

```
agora/
├── agora/
│   ├── __init__.py
│   ├── main.py              # FastAPI app, routes
│   ├── models.py            # SQLAlchemy models
│   ├── schemas.py           # Pydantic schemas (Agent Card, responses)
│   ├── database.py          # DB connection, session management
│   ├── crud.py              # Database operations
│   ├── health_checker.py    # Background health monitoring
│   └── templates/           # Jinja2 templates
│       ├── base.html
│       ├── index.html
│       ├── search.html
│       ├── agent.html
│       └── register.html
├── tests/
│   ├── test_api.py
│   ├── test_validation.py
│   └── test_health.py
├── alembic/                 # Database migrations
├── Dockerfile
├── docker-compose.yml
├── requirements.txt
├── pyproject.toml
├── README.md
├── SPEC.md                  # This file
└── LICENSE                  # MIT
```

---

## Implementation Order

### Phase 1: Core API (Priority)
1. Database models and migrations
2. Agent registration endpoint
3. Agent listing/search endpoint
4. Agent detail endpoint
5. Basic validation

### Phase 2: Ownership & Updates
6. API key hashing and storage
7. Update endpoint with key verification
8. Delete endpoint

### Phase 3: Health Monitoring
9. Background health check task
10. Health status filtering

### Phase 4: Web UI
11. Base template
12. Home page
13. Search page
14. Agent detail page
15. Registration form

### Phase 5: Polish
16. Rate limiting
17. Logging and monitoring
18. Docker deployment
19. Documentation

---

## Testing

### Unit Tests
- Schema validation
- CRUD operations
- API key hashing

### Integration Tests
- Full API flow (register → search → update → delete)
- Health check simulation
- Rate limiting

### Test Data
Create 3-5 sample agents for development:
- Weather Agent
- Research Agent
- Code Agent
- Translation Agent

---

## Beyond Agents: The ERC-8004 Vision

While Agora's MVP focuses on **A2A agent discovery**, the broader vision aligns with ERC-8004's "Trustless Agents" standard, which is actually **service-agnostic trust infrastructure** for the machine economy.

### What ERC-8004 Actually Supports

The standard's registration format accepts:
- **A2A endpoints** - AI agents (our MVP focus)
- **MCP endpoints** - Tool servers, data connectors, APIs
- **Plain URLs** - Any HTTP service
- **ENS names** - On-chain identity
- **DIDs** - Decentralized identity
- **OASF endpoints** - Agent framework interop

The reputation system uses generic metrics (`uptime`, `responseTime`, `successRate`) that apply to **any service with an endpoint**, not just agents.

### Why This Matters

> "The real unlock isn't agents discovering other agents. It's agents discovering and evaluating **any service, tool, or resource** they might need, and doing so through a shared, permissionless trust layer."  
> — Vitto Rivabella, ["You're Reading 8004 Wrong"](https://x.com/VittoStack)

Agents don't need to natively implement every capability. They become **orchestrators** that discover and route to the best service provider for each task.

### Our Architecture Already Supports This

Our database schema is designed for expansion:
- `agent_card` field is JSONB (accepts any registration format)
- Health metrics align with ERC-8004 Reputation Registry
- Skills/capabilities/tags are generic arrays

**Evolutionary path:**
1. **Phase 1 (MVP):** A2A agents only
2. **Phase 2:** MCP tool servers (real demand today)
3. **Phase 3:** General service registry (oracles, APIs, DeFi services)

Marketing stays narrow ("Agent Discovery") but architecture stays broad.

---

## Future Considerations

Things explicitly NOT in MVP but worth noting for future:

1. **Expand Beyond A2A** - Support MCP servers, oracles, general services (ERC-8004 vision)
2. **Federation** - Allow multiple Agora instances to sync
3. **Reputation** - Track successful interactions, build trust scores
4. **Categories** - Official taxonomy of agent types
5. **Verified Agents** - Some form of identity verification
6. **Analytics** - Track searches, popular agents
7. **Webhooks** - Notify agents when searched/connected
8. **Payment Integration** - Tie into Trustee for paid agent services

---

## Success Criteria

MVP is successful if:
1. ✅ Can register ada-home as first agent
2. ✅ Can search and find ada-home by skill
3. ✅ Health monitoring shows ada-home as healthy
4. ✅ At least 5 other agents register within 1 month
5. ✅ Service stays up for 30 days without major incidents

---

## Implementation Details (Interview Decisions - 2026-02-16)

This section captures decisions from the requirements interview and is implementation-authoritative for MVP. If any earlier section conflicts with this section, this section wins.

### 1. Overview

The MVP remains a neutral A2A registry with open discovery and API-key ownership. This update locks down edge behavior in four critical areas: ownership recovery, search semantics, URL identity normalization, and stale-agent handling.

Key product posture:
- Conservative on destructive behavior (no auto-removal in MVP)
- Explicit and debuggable ownership recovery flow
- Predictable filtering and sort behavior for discovery clients
- Minimal schema expansion to support correctness (`last_healthy_at`)

### 2. Requirements (Functional + Edge Cases)

#### 2.1 Functional Requirements

1. URL immutability:
- Agent URL is the identity anchor.
- `PUT /agents/{id}` must reject URL changes.
- Endpoint migration is out of scope for MVP and must use delete + re-register.

2. Ownership recovery (proof-of-control):
- Support a two-step recovery flow:
  - `POST /agents/{id}/recovery/start`
  - `POST /agents/{id}/recovery/complete`
- Proof is serving a challenge token at `/.well-known/agora-verify` on the agent origin.
- On successful complete, rotate ownership to a new API key provided by client in `X-API-Key`.

3. Search/filter semantics:
- Repeated filters use OR within a filter type.
- Different filter types combine with AND.
- `q` uses case-insensitive `ILIKE` matching in MVP.

4. Stale behavior:
- No auto-removal in MVP.
- Support `stale=true|false` filter.
- Expose computed `is_stale` and `stale_days` in responses.

5. Default ordering:
- `/agents` default sort is health-first, then newest registration:
  - `healthy`
  - `unknown`
  - `unhealthy`
  - within each group: `registered_at DESC`

#### 2.2 Edge Case Requirements

1. Never-healthy agents:
- If `health_status = unhealthy` and `last_healthy_at IS NULL`, compute staleness from `registered_at`.

2. Unknown is not stale:
- `unknown` health status must never be marked stale.

3. Recovery token replacement:
- Only one active recovery token per agent.
- Calling `recovery/start` invalidates any prior unexpired token.

4. Recovery on unknown ID:
- Return `404`.
- Apply rate limiting and abuse logging to recovery endpoints.

5. URL duplicate prevention:
- Apply strict URL normalization before uniqueness checks and persistence.

### 3. Technical Specification (Architecture, Data Model, APIs)

#### 3.1 Architecture and Behavior

1. URL canonicalization is a required pre-write step for register/update validation.
2. Recovery verification reuses existing outbound HTTP capability from health-check infrastructure.
3. Concurrent updates use last-write-wins in MVP.

#### 3.2 Data Model

Add to `agents` table:

```sql
ALTER TABLE agents
  ADD COLUMN last_healthy_at TIMESTAMP NULL,
  ADD COLUMN recovery_challenge_hash VARCHAR(64) NULL,
  ADD COLUMN recovery_challenge_expires_at TIMESTAMP NULL,
  ADD COLUMN recovery_challenge_created_at TIMESTAMP NULL;

CREATE INDEX idx_agents_last_healthy_at ON agents (last_healthy_at);
```

Notes:
- Keep existing `url` column as unique identity field.
- Persist URL in normalized canonical form in `url`.
- Store recovery challenge as SHA-256 hash, not plaintext.

#### 3.3 URL Normalization Rules (Strict)

Apply before register/update comparison and before DB write:

1. Parse URL; only `http` and `https` are allowed.
2. Lowercase scheme and host.
3. Remove default ports (`:80` for HTTP, `:443` for HTTPS).
4. Strip trailing slash from path except root `/`.
5. Preserve path and query exactly (no query reordering).
6. Drop URL fragment.

Examples:
- `https://Agent.Example.com:443/a2a/` -> `https://agent.example.com/a2a`
- `https://agent.example.com/a2a?x=1` -> `https://agent.example.com/a2a?x=1`

#### 3.4 API Contracts

##### 3.4.1 List/Search Agents

`GET /agents`

Add query parameter:
- `stale` (boolean): `true` or `false`

Filter semantics:
- OR within same type, AND across different types.
- Example:
  - `?skill=weather&skill=translation` => skill is weather OR translation
  - `?skill=weather&health=healthy` => skill matches AND health is healthy

Text search:
- `q` is implemented with `ILIKE` across name, description, skills, and tags.

Default ordering:
- `healthy` first, then `unknown`, then `unhealthy`, then `registered_at DESC`.

##### 3.4.2 Recovery Start

`POST /agents/{id}/recovery/start`

Behavior:
1. Validate agent exists, else `404`.
2. Generate random challenge token.
3. Hash token (SHA-256) and store hash + expiry + created time.
4. Invalidate any previously active token for this agent.
5. Return plaintext token once to caller.

Response:

```json
{
  "agent_id": "uuid",
  "challenge_token": "random-token",
  "verify_url": "https://agent.example.com/.well-known/agora-verify",
  "expires_at": "2026-02-16T12:15:00Z"
}
```

Status codes:
- `200` success
- `404` agent not found
- `429` rate limited

##### 3.4.3 Recovery Complete

`POST /agents/{id}/recovery/complete`  
Header: `X-API-Key: <new-client-generated-key>`

Behavior:
1. Validate agent exists, else `404`.
2. Validate active unexpired challenge exists, else `400`.
3. Fetch `https://<agent-origin>/.well-known/agora-verify` (10s timeout).
4. Response body must be plain text exactly equal to the active challenge token.
5. If valid, hash provided new API key and replace `owner_key_hash`.
6. Clear challenge fields.

Status codes:
- `200` key rotated
- `400` no active challenge, expired challenge, or verification mismatch
- `404` agent not found
- `429` rate limited

##### 3.4.4 Update Agent

`PUT /agents/{id}`

Additional enforced behavior:
- URL in submitted Agent Card, after normalization, must match stored URL exactly.
- If not equal, return `400` with URL-immutable error.

#### 3.5 Health and Stale Computation

Definitions:
- `STALE_THRESHOLD_DAYS = 7` (MVP default)

On health check success:
- `health_status = healthy`
- `last_health_check = now`
- `last_healthy_at = now`

On health check failure:
- `health_status = unhealthy`
- `last_health_check = now`
- `last_healthy_at` unchanged

Stale function:
1. If `health_status != unhealthy`: `is_stale = false`
2. Else if `last_healthy_at IS NOT NULL`: stale if `now - last_healthy_at > threshold`
3. Else (never healthy): stale if `now - registered_at > threshold`

`stale=true` filter:
- Return only rows where `is_stale = true`

`stale=false` filter:
- Return all rows where `is_stale = false` (includes healthy, unknown, and recently unhealthy)

No auto-removal:
- Disable 30-day auto-delete behavior for MVP.
- Stale is advisory only for manual review.

#### 3.6 Response Shape Additions

Add computed fields:
- `is_stale` (boolean)
- `stale_days` (integer, 0 when not stale)

Expose in:
- `GET /agents` items
- `GET /agents/{id}`
- `GET /registry.json` entries

### 4. UI/UX Specification

1. Search UI:
- Add stale filter control (`All`, `Stale only`, `Not stale`).
- Keep existing skill/capability/health filters.

2. Result cards:
- Show health badge and stale badge when `is_stale = true`.
- Preserve mobile responsiveness.

3. Agent detail page:
- Show computed stale metadata (`is_stale`, `stale_days`, `last_healthy_at`, `last_health_check`).
- If stale, show non-destructive warning ("Candidate for manual review").

4. Registration/update UX:
- Clearly indicate URL immutability after initial registration.
- Show normalized URL in validation feedback.

5. Recovery UX:
- Step 1 screen: display token + verify URL + expiration timer.
- Step 2 screen: submit new API key and run verification.
- Show explicit failure states: expired token, token mismatch, endpoint unreachable.

### 5. Constraints & Assumptions

1. MVP constraints:
- No endpoint migration workflow.
- No auto-removal of stale agents.
- Last-write-wins on concurrent updates.

2. Security constraints:
- Recovery endpoints must be rate-limited.
- Recovery attempts must be logged with timestamp, agent ID, source IP, and outcome.
- Recovery challenge tokens are never logged in plaintext.

3. Operational assumptions:
- Health checker HTTP client timeout remains 10 seconds.
- Recovery verification uses same timeout and outbound egress rules.
- Agent IDs are publicly discoverable; anti-enumeration by obscurity is not required.

4. Suggested recovery limits (MVP defaults):
- `POST /recovery/start`: 5/hour per IP, 3/hour per agent
- `POST /recovery/complete`: 10/hour per IP, 5/hour per agent

### 6. Open Questions

No blocking open questions for MVP implementation.  
Post-MVP candidates:
- Add optimistic concurrency (`If-Match` / ETag)
- Upgrade search to Postgres full-text or trigram
- Revisit auto-removal once false-positive rate is understood in production

### 7. Appendix (Interview Notes and Rationale)

Final decisions from interview:
1. `1C` URL immutable; migration out of scope for MVP
2. `2B` Proof-of-control recovery flow
3. `3B + ILIKE` OR within filter type, AND across types; text search via ILIKE
4. `4C` No auto-removal in MVP; stale exposed via filter + computed fields
5. `1A` Recovery flow is two-step (`start` then `complete`)
6. `2A` Strict URL normalization
7. `3C` Unknown agent recovery returns `404` + rate limiting and abuse logging
8. `4C` Default ordering health-first then `registered_at DESC`
9. `1A` Add `last_healthy_at` for correct stale computation
10. `2A` Verify at origin-level `/.well-known/agora-verify`, plain text token
11. `1A` One active token per agent; new `start` invalidates prior token
12. `2A` Client supplies new key in `X-API-Key` on `complete`
13. `3A` `stale=true` only for long-unhealthy, including never-healthy fallback from `registered_at`
14. `4C` Keep single source of truth in `SPEC.md`

---

## References

- [A2A Protocol Specification](https://a2a-protocol.org/latest/specification/)
- [A2A Agent Card Schema](https://a2a-protocol.org/latest/specification/#55-agentcard-object-structure)
- [ERC-8004: Trustless Agents](https://ethereum-magicians.org/t/erc-8004-autonomous-agent-identity/22268)
- [You're Reading 8004 Wrong (Vitto Rivabella)](https://x.com/VittoStack) - Why ERC-8004 is service-agnostic trust infrastructure
- [Our Agent Coordination Research](../workspace/obsidian-vault/Research/Agent%20Coordination%20Infrastructure%202026.md)

---

*This spec is the source of truth for MVP implementation. Questions or clarifications should be added as GitHub issues.*
