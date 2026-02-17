# Agora

Agora is an open registry for A2A-compatible agents.  
You can register an agent card, search/discover agents, and recover ownership if keys are lost.

## Status

MVP is complete through Milestone I in `IMPLEMENTATION_TASKS.md`.

## Start Here

- New to the project: `docs/QUICKSTART.md`
- Want end-to-end API examples: `docs/FIRST_AGENT_API.md`
- Need recovery steps: `docs/RECOVERY.md`
- Running in production/devops mode: `docs/OPERATIONS.md`
- Hit an error: `docs/TROUBLESHOOTING.md`
- Full endpoint catalog: `docs/API_REFERENCE.md`

## 2-Minute Bring-Up (Docker)

Use either command style depending on your Docker install:

```bash
docker compose up --build
# or
docker-compose up --build
```

Then verify:

```bash
curl http://localhost:8000/api/v1/health
```

Open:
- UI: `http://localhost:8000/`
- Swagger docs: `http://localhost:8000/docs`

## Local Dev (No Docker)

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

cp .env.example .env
alembic upgrade head
uvicorn agora.main:app --reload
```

## Seed Sample Agents

```bash
python scripts/seed_sample_agents.py --base-url http://localhost:8000
```

This seeds weather, research, code, and translation example agents.

## Test Suite

```bash
./.venv/bin/pytest -q
```

## Project References

- Requirements/spec: `SPEC.md`
- Implementation checklist: `IMPLEMENTATION_TASKS.md`
- MVP sign-off: `MVP_SIGNOFF_CHECKLIST.md`

## License

MIT. See `LICENSE`.
