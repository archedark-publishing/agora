# Agora MVP Sign-off Checklist

Date: 2026-02-17

## Product Scope

- [x] Agent registration, update, delete, and ownership verification are implemented.
- [x] Recovery start/complete flow is implemented with single active challenges.
- [x] Recovery abuse controls (rate limits + logging) are active.
- [x] Health monitoring and stale computation are implemented.
- [x] No automated stale deletion is enabled for MVP.
- [x] Registry export endpoint serves cached snapshots.
- [x] Web UI pages for home/search/detail/register/recover are implemented.

## Security and Operations

- [x] Core API and recovery endpoint rate limits are enforced.
- [x] SSRF protection blocks private/internal targets by default.
- [x] User-supplied strings are sanitized before persistence and safely rendered.
- [x] Request logs and metrics endpoint are implemented.

## Test and Release Readiness

- [x] Unit tests for normalization, validation, key hashing, and stale logic are present.
- [x] Integration tests cover lifecycle, recovery, stale filters, and ordering semantics.
- [x] `pytest -q` is passing locally.
- [x] Docker assets are present (`Dockerfile`, `docker-compose.yml`).
- [ ] Compose boot verification (`docker compose config` / `docker compose up`) requires Docker CLI, which is not available in this execution environment.
- [x] Seed script for sample agents is available (`scripts/seed_sample_agents.py`).

## Final Go/No-go

- [x] MVP P0 scope from `IMPLEMENTATION_TASKS.md` is complete.
- [x] Milestone I (`I1`-`I6`) is complete.
