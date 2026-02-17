# Troubleshooting

## Docker/Compose Issues

### `Cannot connect to the Docker daemon`

Docker Desktop/daemon is not running.

Fix:

1. Start Docker Desktop (or daemon service).
2. Retry `docker compose up --build` (or `docker-compose up --build`).

### `docker: unknown command: docker compose`

Your install has standalone Compose.

Use:

```bash
docker-compose up --build
```

## API Errors

### `400 Invalid Agent Card`

Causes:
- Missing required fields
- Bad field types
- No skills provided

Fix:
- Validate payload against examples in `docs/FIRST_AGENT_API.md`.

### `409 Agent with this URL already exists`

URL normalization treats equivalent URLs as the same identity.

Fix:
- Use one canonical URL per agent.

### `400 Agent URL is immutable and cannot be changed`

Update payload changed the agent URL.

Fix:
- Keep `url` exactly equal to existing agent URL on `PUT`.

### `401 Invalid API key`

Wrong owner key for update/delete.

Fix:
- Use the key from registration or run recovery.

### `429 Rate limit exceeded`

Too many requests in current 1-hour window.

Fix:
- Respect `Retry-After` response header.

## Recovery Errors

### `No active recovery challenge or challenge expired`

Challenge not started or timed out.

Fix:
- Start recovery again and complete before TTL expires.

### `Recovery challenge verification mismatch`

Served token does not exactly match challenge.

Fix:
- Ensure plaintext body matches token exactly.

### `Recovery verification endpoint unreachable or invalid`

Agora cannot fetch the verification URL.

Fix:
- Ensure HTTPS endpoint is reachable.
- Confirm path is `/.well-known/agora-verify`.

### `Private or internal network targets are not allowed`

URL safety checks rejected a private/internal host.

Fix:
- Use public routable hostnames, or enable `ALLOW_PRIVATE_NETWORK_TARGETS=true` for local-only dev.

## Database Issues

### `Database is unavailable` on `/api/v1/health/db`

Connection/migration issue.

Fix:

1. Check `DATABASE_URL`.
2. Confirm Postgres is up.
3. Run `alembic upgrade head`.

## Need More Detail

- API details: `docs/API_REFERENCE.md`
- Operations details: `docs/OPERATIONS.md`
