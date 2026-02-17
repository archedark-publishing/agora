# Agora

Agora is an open registry for A2A-compatible agents.
It gives agent owners a common place to publish Agent Cards, and gives users and systems a reliable way to discover, verify, and recover agents.

## Why the name "Agora"?

In ancient Greece, the *agora* was the central public square: part marketplace, part meeting place, part civic hub.
The name fits this project because Agora serves a similar role for agents: an open, shared place where capabilities can be announced, discovered, and trusted.

## Project Status

| Item | Value |
|---|---|
| Maturity | Production-ready MVP |
| Version | `0.1.0` |
| Python | `>=3.11` |
| License | MIT |

## What Agora Provides

- Agent registration using A2A-style Agent Cards
- Search and discovery with practical filtering
- Owner-authenticated update and delete flows
- Recovery flow for API key loss via origin verification
- Cached `registry.json` export for ecosystem consumption
- Built-in health checks, stale detection, and rate limiting

## 60-Second Smoke Test (Docker)

Use either Compose command style depending on your Docker install:

```bash
export ADMIN_API_TOKEN="$(openssl rand -hex 24)"
export POSTGRES_PASSWORD="$(openssl rand -hex 24)"
export REDIS_PASSWORD="$(openssl rand -hex 24)"
docker compose up --build
# or
docker-compose up --build
```

Verify:

```bash
curl http://localhost:8000/api/v1/health
```

Open:

- UI: `http://localhost:8000/`
- API docs (Swagger): `http://localhost:8000/docs`

For full setup options (Docker and local Python), see `docs/QUICKSTART.md`.

## Architecture At A Glance

```mermaid
flowchart LR
    A[Clients / UIs / Integrations] --> B[FastAPI Service]
    B --> C[(PostgreSQL)]
    B --> D[(Redis - optional)]
    B --> E[/api/v1/registry.json cache]
    B --> F[Background jobs: health checker + registry refresher]
```

## Docs By Task

| If you want to... | Read |
|---|---|
| Get running quickly | `docs/QUICKSTART.md` |
| Walk through full agent lifecycle via API | `docs/FIRST_AGENT_API.md` |
| Rotate ownership keys after key loss | `docs/RECOVERY.md` |
| See endpoint list and status codes | `docs/API_REFERENCE.md` |
| Tune env vars, rate limits, and operations | `docs/OPERATIONS.md` |
| Diagnose common failures | `docs/TROUBLESHOOTING.md` |
| Browse docs index | `docs/README.md` |

## Repository Map

- `agora/`: FastAPI app, models, validation, security, templates
- `alembic/`: database migrations
- `scripts/`: utility scripts (for example, seeding sample agents)
- `tests/`: unit and integration test suites
- `docs/`: operational and API documentation

## Security And Trust Model

Agora is designed as a public-facing registry with defensive defaults:

- URL safety checks to reduce SSRF exposure
- Recovery challenge + session flow for ownership rotation
- Per-endpoint rate limits and bounded metrics
- Stale classification as advisory signal (not auto-deletion in MVP)

Details live in:

- `docs/OPERATIONS.md`
- `docs/RECOVERY.md`
- `docs/API_REFERENCE.md`

## MVP Non-Goals

- Automatic deletion of stale agents
- Acting as an agent execution/runtime platform
- Allowing private/internal network targets by default

## Testing

```bash
./.venv/bin/pytest -q
```

## License

MIT. See `LICENSE`.
