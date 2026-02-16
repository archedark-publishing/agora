# Agora MVP Implementation Task List

Source of truth: `SPEC.md` (including `Implementation Details (Interview Decisions - 2026-02-16)`).

This is an issue-ready, dependency-ordered task list for implementation.

## Execution Plan

1. Milestone A: Foundation and Data Model
2. Milestone B: Core Read APIs
3. Milestone C: Ownership Write APIs
4. Milestone D: Recovery Flow
5. Milestone E: Health Monitoring and Stale Logic
6. Milestone F: Registry Export
7. Milestone G: Web UI
8. Milestone H: Security, Rate Limiting, and Observability
9. Milestone I: Test Suite and Release Readiness

## Milestone A: Foundation and Data Model

### A1. Project scaffolding and app wiring
- Priority: P0
- Depends on: none
- Deliverables:
  - FastAPI app entrypoint in `agora/main.py`
  - Config module for env vars in `agora/config.py`
  - Async DB session setup in `agora/database.py`
- Acceptance criteria:
  - App boots with `uvicorn agora.main:app --reload`
  - DB health check route can run a simple query

### A2. SQLAlchemy models for `agents`
- Priority: P0
- Depends on: A1
- Deliverables:
  - `agora/models.py` with all schema fields from `SPEC.md`
  - Include new fields:
    - `last_healthy_at`
    - `recovery_challenge_hash`
    - `recovery_challenge_expires_at`
    - `recovery_challenge_created_at`
- Acceptance criteria:
  - Model definitions match spec types and constraints
  - URL column remains unique identity anchor

### A3. Alembic migrations
- Priority: P0
- Depends on: A2
- Deliverables:
  - Initial migration for `agents` table + indexes
  - Migration scripts checked in under `alembic/versions/`
- Acceptance criteria:
  - `alembic upgrade head` works on empty database
  - Indexes exist for `skills`, `capabilities`, `tags`, `health_status`, `name`, `last_healthy_at`

### A4. URL normalization utility
- Priority: P0
- Depends on: A1
- Deliverables:
  - `agora/url_normalization.py` utility implementing strict canonicalization:
    - lowercase scheme/host
    - remove default ports
    - strip trailing slash except root
    - preserve path/query
    - drop fragments
- Acceptance criteria:
  - Deterministic normalized output for equivalent URLs
  - Invalid schemes rejected (`http`/`https` only)

### A5. A2A Agent Card validation service
- Priority: P0
- Depends on: A1
- Deliverables:
  - `agora/validation.py` with Agent Card validation
  - Enforce required fields and at least one skill
- Acceptance criteria:
  - Invalid cards return structured validation errors
  - Valid cards pass and expose extracted fields (skills, tags, capabilities)

## Milestone B: Core Read APIs

### B1. Register agent endpoint
- Priority: P0
- Depends on: A2, A4, A5
- Endpoint: `POST /api/v1/agents`
- Deliverables:
  - Normalize URL before uniqueness check and persistence
  - Store full `agent_card` JSON and extracted search fields
  - Return 201 response contract from spec
- Acceptance criteria:
  - Duplicate normalized URL returns 409
  - Invalid card returns 400

### B2. Agent detail endpoint
- Priority: P0
- Depends on: A2
- Endpoint: `GET /api/v1/agents/{id}`
- Deliverables:
  - Return full Agent Card + metadata
  - Include computed `is_stale` and `stale_days`
- Acceptance criteria:
  - 404 for unknown ID
  - Response shape matches spec

### B3. List/search endpoint with filter semantics
- Priority: P0
- Depends on: A2, A4
- Endpoint: `GET /api/v1/agents`
- Deliverables:
  - Pagination (`limit`, `offset`)
  - Filter semantics:
    - OR within filter type
    - AND across filter types
  - `q` uses `ILIKE`
  - `stale=true|false` query support
  - Default sort: healthy -> unknown -> unhealthy, then `registered_at DESC`
- Acceptance criteria:
  - Query behavior matches interview decisions
  - Includes `total`, `limit`, `offset`

### B4. Health endpoint
- Priority: P1
- Depends on: A1, A2
- Endpoint: `GET /api/v1/health`
- Deliverables:
  - Return status, version, agents_count, uptime_seconds
- Acceptance criteria:
  - Healthy response under normal operation
  - DB unavailable path returns non-healthy status

## Milestone C: Ownership Write APIs

### C1. API key hashing and verification helpers
- Priority: P0
- Depends on: A1
- Deliverables:
  - SHA-256 hash helper for key storage
  - Constant-time compare helper for incoming key checks
- Acceptance criteria:
  - Raw API key is never persisted or logged

### C2. Update agent endpoint (URL immutable)
- Priority: P0
- Depends on: B1, C1, A4, A5
- Endpoint: `PUT /api/v1/agents/{id}`
- Deliverables:
  - Require valid API key
  - Validate updated card
  - Enforce normalized URL exact match with stored URL
- Acceptance criteria:
  - URL changes rejected with 400
  - Invalid key returns 401

### C3. Delete agent endpoint
- Priority: P0
- Depends on: C1
- Endpoint: `DELETE /api/v1/agents/{id}`
- Deliverables:
  - API key-gated deletion
- Acceptance criteria:
  - Valid key deletes and returns 204
  - Invalid key returns 401

## Milestone D: Recovery Flow

### D1. Recovery start endpoint
- Priority: P0
- Depends on: C1, A2
- Endpoint: `POST /api/v1/agents/{id}/recovery/start`
- Deliverables:
  - Generate plaintext challenge token
  - Store only SHA-256 hash + expiration + created_at
  - Invalidate prior active challenge (single active token rule)
  - Return token once with verify URL and expires_at
- Acceptance criteria:
  - Unknown ID returns 404
  - New start invalidates previous token

### D2. Recovery complete endpoint
- Priority: P0
- Depends on: D1, C1
- Endpoint: `POST /api/v1/agents/{id}/recovery/complete`
- Headers: `X-API-Key` (new client-generated key)
- Deliverables:
  - Fetch `https://<origin>/.well-known/agora-verify`
  - Verify plain response body exactly matches active challenge token
  - Rotate `owner_key_hash`
  - Clear recovery challenge fields
- Acceptance criteria:
  - Expired or missing challenge returns 400
  - Verification mismatch returns 400
  - Success rotates key and returns 200

### D3. Recovery endpoint abuse controls
- Priority: P0
- Depends on: D1, D2
- Deliverables:
  - Rate limits for start/complete
  - Abuse logging with source IP, agent ID, outcome
- Acceptance criteria:
  - Rate-limited calls return 429 + `Retry-After`
  - Plain challenge token never written to logs

## Milestone E: Health Monitoring and Stale Logic

### E1. Background health checker
- Priority: P0
- Depends on: A2
- Deliverables:
  - Hourly async job
  - Fetch `/.well-known/agent-card.json` with 10s timeout
  - Check only agents queried in last 24h
- Acceptance criteria:
  - Healthy check updates status and timestamps
  - Failure marks unhealthy without crashing worker

### E2. `last_healthy_at` update semantics
- Priority: P0
- Depends on: E1
- Deliverables:
  - On success: set `last_healthy_at = now`
  - On failure: leave `last_healthy_at` unchanged
- Acceptance criteria:
  - Never-healthy agents keep `last_healthy_at = NULL`

### E3. Shared stale computation service
- Priority: P0
- Depends on: E2
- Deliverables:
  - `is_stale` and `stale_days` computation utility
  - Logic:
    - stale only if currently unhealthy
    - use `last_healthy_at` when present
    - fallback to `registered_at` when never healthy
- Acceptance criteria:
  - Unknown agents are never stale
  - Logic is reused by API and UI serializers

### E4. Disable auto-removal for MVP
- Priority: P0
- Depends on: E1
- Deliverables:
  - Ensure no background process auto-deletes stale agents
  - Optional admin-only report of stale candidates
- Acceptance criteria:
  - No deletes occur based on staleness alone

## Milestone F: Registry Export

### F1. Registry generation job
- Priority: P1
- Depends on: B3, E3
- Deliverables:
  - Hourly `/registry.json` generation
  - Include full card + metadata + stale computed fields
- Acceptance criteria:
  - `generated_at` and `agents_count` accurate

### F2. Serve export endpoint
- Priority: P1
- Depends on: F1
- Endpoint: `GET /api/v1/registry.json`
- Deliverables:
  - Serve most recent snapshot
  - CDN-friendly cache headers
- Acceptance criteria:
  - Endpoint stable under repeated fetches

## Milestone G: Web UI

### G1. Base layout and shared components
- Priority: P1
- Depends on: A1
- Deliverables:
  - `base.html` with mobile-responsive layout
  - Shared badges for health/stale states

### G2. Home page
- Priority: P1
- Depends on: B3, B4
- Route: `/`
- Deliverables:
  - Search bar, recent agents, platform stats

### G3. Search results page
- Priority: P1
- Depends on: B3, E3
- Route: `/search`
- Deliverables:
  - Filters: skill, capability, health, stale
  - Pagination and sorting display
- Acceptance criteria:
  - `stale=true|false` controls map correctly to API

### G4. Agent detail page
- Priority: P1
- Depends on: B2
- Route: `/agent/{id}`
- Deliverables:
  - Full card render
  - `is_stale`, `stale_days`, `last_healthy_at`, `last_health_check`
  - Non-destructive stale warning

### G5. Register page
- Priority: P1
- Depends on: B1
- Route: `/register`
- Deliverables:
  - Card JSON submission form
  - API key input/generation helper
  - Explicit URL immutability guidance

### G6. Recovery UI
- Priority: P1
- Depends on: D1, D2
- Route: `/recover` (or equivalent)
- Deliverables:
  - Step 1: start challenge and display token/expiry
  - Step 2: submit new key and complete verification
  - Clear error states (expired, mismatch, endpoint unreachable)

## Milestone H: Security, Rate Limiting, and Observability

### H1. Endpoint rate limiting
- Priority: P0
- Depends on: A1
- Deliverables:
  - Sliding window limits per spec for read/write endpoints
  - Recovery-specific limits from implementation details
- Acceptance criteria:
  - 429 response includes `Retry-After`

### H2. SSRF and URL safety protections
- Priority: P0
- Depends on: A4
- Deliverables:
  - Block private/internal IP targets for agent URLs
  - Safe outbound request policy for health/recovery checks

### H3. Input sanitization and output safety
- Priority: P0
- Depends on: A5
- Deliverables:
  - Sanitize text fields rendered in UI
  - Ensure templates escape unsafe content by default

### H4. Structured logs and metrics
- Priority: P1
- Depends on: A1
- Deliverables:
  - Request logs with status/latency
  - Recovery abuse logs
  - Health check summary metrics

## Milestone I: Test Suite and Release Readiness

### I1. Unit tests
- Priority: P0
- Depends on: A4, A5, C1, E3
- Deliverables:
  - URL normalization cases
  - Agent Card validation cases
  - API key hash/verify
  - Stale computation matrix

### I2. Integration tests for lifecycle
- Priority: P0
- Depends on: B1, B2, B3, C2, C3
- Deliverables:
  - Register -> search -> detail -> update -> delete
  - URL immutability rejection

### I3. Integration tests for recovery flow
- Priority: P0
- Depends on: D1, D2, D3
- Deliverables:
  - Start -> serve token -> complete -> old key fails -> new key works
  - Expired token and mismatch paths
  - Multiple start invalidates prior token

### I4. Integration tests for health/stale
- Priority: P0
- Depends on: E1, E2, E3
- Deliverables:
  - Never-healthy stale fallback from `registered_at`
  - Unknown never stale
  - `stale=true` and `stale=false` filter behavior

### I5. Integration tests for search semantics and ordering
- Priority: P0
- Depends on: B3
- Deliverables:
  - OR-within-type and AND-across-type assertions
  - `ILIKE` search behavior
  - Default health-tier ordering assertions

### I6. Release checklist and docs updates
- Priority: P1
- Depends on: all prior milestones
- Deliverables:
  - Update `README.md` with setup and endpoint status
  - Confirm Docker and compose boot
  - Seed script for sample agents (weather, research, code, translation)
  - MVP sign-off checklist

## Suggested Issue Batching

Batch 1 (must merge first): A1-A5, B1-B3, C1-C3  
Batch 2: D1-D3, E1-E4, H1-H3  
Batch 3: F1-F2, G1-G6, H4  
Batch 4: I1-I6

## MVP Done Definition

MVP is done when all P0 tasks are complete and integration tests for lifecycle, recovery, stale filtering, and ordering are green in CI.
