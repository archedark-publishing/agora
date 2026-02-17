# Agora

Open agent discovery platform built around A2A Agent Cards.

## Status

MVP implementation is complete through Milestone I in `IMPLEMENTATION_TASKS.md`.

## Local Setup

1. Create and activate a virtual environment.
2. Install dependencies.
3. Configure `DATABASE_URL`.
4. Run migrations.
5. Start the API server.

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

export DATABASE_URL='postgresql+asyncpg://agora:password@localhost:5432/agora'
alembic upgrade head
uvicorn agora.main:app --reload
```

## Test Suite

```bash
./.venv/bin/pytest -q
```

## Docker Compose

```bash
docker compose up --build
```

Services:
- `api`: FastAPI app on `http://localhost:8000`
- `db`: PostgreSQL 16 on `localhost:5432`

Compose configuration validation:

```bash
docker compose config
```

## Endpoint Status

Implemented API endpoints:
- `GET /api/v1`
- `GET /api/v1/health`
- `GET /api/v1/health/db`
- `POST /api/v1/agents`
- `GET /api/v1/agents`
- `GET /api/v1/agents/{id}`
- `PUT /api/v1/agents/{id}`
- `DELETE /api/v1/agents/{id}`
- `POST /api/v1/agents/{id}/recovery/start`
- `POST /api/v1/agents/{id}/recovery/complete`
- `GET /api/v1/registry.json`
- `GET /api/v1/metrics`
- `GET /api/v1/admin/stale-candidates` (requires `X-Admin-Token`)

Implemented web routes:
- `/`
- `/search`
- `/agent/{id}`
- `/register`
- `/recover`

## Seed Script

Seed four sample agents (weather, research, code, translation):

```bash
python scripts/seed_sample_agents.py --base-url http://localhost:8000
```

## MVP Sign-off

Release readiness checklist is tracked in `MVP_SIGNOFF_CHECKLIST.md`.

## References

- `SPEC.md`
- `IMPLEMENTATION_TASKS.md`
- `MVP_SIGNOFF_CHECKLIST.md`

## License

MIT. See `LICENSE`.
