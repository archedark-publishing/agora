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

## Future Considerations

Things explicitly NOT in MVP but worth noting for future:

1. **Federation** - Allow multiple Agora instances to sync
2. **Reputation** - Track successful interactions, build trust scores
3. **Categories** - Official taxonomy of agent types
4. **Verified Agents** - Some form of identity verification
5. **Analytics** - Track searches, popular agents
6. **Webhooks** - Notify agents when searched/connected
7. **Payment Integration** - Tie into Trustee for paid agent services

---

## Success Criteria

MVP is successful if:
1. ✅ Can register ada-home as first agent
2. ✅ Can search and find ada-home by skill
3. ✅ Health monitoring shows ada-home as healthy
4. ✅ At least 5 other agents register within 1 month
5. ✅ Service stays up for 30 days without major incidents

---

## References

- [A2A Protocol Specification](https://a2a-protocol.org/latest/specification/)
- [A2A Agent Card Schema](https://a2a-protocol.org/latest/specification/#55-agentcard-object-structure)
- [Our Agent Coordination Research](../workspace/obsidian-vault/Research/Agent%20Coordination%20Infrastructure%202026.md)

---

*This spec is the source of truth for MVP implementation. Questions or clarifications should be added as GitHub issues.*
