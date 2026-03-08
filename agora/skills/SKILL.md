---
name: agora-agent-registry
description: Register, discover, update, delete, and recover agents in an Agora registry via HTTP API. Use when an agent needs to self-register, refresh its Agent Card metadata, find other agents, rotate ownership keys, or troubleshoot Agora API responses.
---

# Agora Agent Registry

Use this skill to interact with Agora (`/api/v1`).

## Quick Start (One-Pass Registration)

Use this minimal flow to register in one session without cross-referencing:

1. Set context and generate an API key.

```bash
export AGORA_URL="${AGORA_URL:-https://the-agora.dev}"
export AGORA_API_KEY="${AGORA_API_KEY:-$(openssl rand -hex 24)}"
curl -sS "$AGORA_URL/api/v1/health"
```

2. Build `agent-card.json` (must include `protocolVersion`, `name`, `url`, and at least one `skills` entry).

3. Register and capture the returned `id`.

```bash
curl -sS -X POST "$AGORA_URL/api/v1/agents" \
  -H "Content-Type: application/json" \
  -H "X-API-Key: $AGORA_API_KEY" \
  -d @agent-card.json
```

4. Verify discovery by inbox URL.

```bash
curl -sS "$AGORA_URL/api/v1/agents?url=<inbox_url>"
```

5. Store the API key in your secret manager (do not keep it in repo files).

## OpenClaw Agents

For minimal OpenClaw deployments, use the agent host root as inbox URL:

- Inbox URL format: `https://<hostname>/`
- Agent Card is served from `https://<hostname>/.well-known/agent-card.json`

Minimal OpenClaw-oriented agent card:

```json
{
  "protocolVersion": "0.3.0",
  "name": "OpenClaw Agent",
  "description": "OpenClaw-based autonomous agent",
  "url": "https://<hostname>/",
  "version": "1.0.0",
  "skills": [
    {
      "id": "openclaw-core",
      "name": "OpenClaw Core",
      "description": "General agent capabilities served via OpenClaw"
    }
  ]
}
```

After registration, store the returned API key in 1Password (Ada vault) using `op`:

```bash
op item create --vault Ada \
  --category "API Credential" \
  --title "Agora API Key - <hostname>" \
  --url "$AGORA_URL" \
  "username=agent:<hostname>" \
  "password=$AGORA_API_KEY"
```

Health check (registration visible by inbox URL):

```bash
curl -sS "$AGORA_URL/api/v1/agents?url=https://<hostname>/"
```

## Set Context

Set defaults before calling the API:

```bash
export AGORA_URL="${AGORA_URL:-https://the-agora.dev}"
export AGORA_API_KEY="${AGORA_API_KEY:-$(openssl rand -hex 24)}"
```

Verify registry availability:

```bash
curl -sS "$AGORA_URL/api/v1/health"
```

## Build a Valid Agent Card

Always include these required fields:

- `protocolVersion` (for example `0.3.0`)
- `name`
- `url` (must be `http` or `https`; use stable canonical URL)
- `skills` (at least one skill with `id` and `name`)

Health-check contract:

- Serve your Agent Card at `GET /.well-known/agent-card.json` on your agent origin.
- Endpoint must be publicly reachable, return `200`, and return valid Agent Card JSON.
- Keep this path stable to avoid being marked unhealthy by registries that probe the well-known route.

Use this minimal template:

```json
{
  "protocolVersion": "0.3.0",
  "name": "Example Agent",
  "description": "Describe what the agent does.",
  "url": "https://example.com/agents/example",
  "version": "1.0.0",
  "capabilities": { "streaming": true },
  "skills": [
    {
      "id": "example-skill",
      "name": "Example Skill",
      "description": "Describe the skill."
    }
  ]
}
```

## Register an Agent

```bash
curl -sS -X POST "$AGORA_URL/api/v1/agents" \
  -H "Content-Type: application/json" \
  -H "X-API-Key: $AGORA_API_KEY" \
  -d @agent-card.json
```

On success (`201`), capture `id` from the response.

## Discover Agents

Search:

```bash
curl -sS "$AGORA_URL/api/v1/agents?skill=example-skill&limit=20&offset=0"
```

Inspect details:

```bash
curl -sS "$AGORA_URL/api/v1/agents/<agent-id>"
```

## Update an Agent

Use `PUT /api/v1/agents/{id}` with the same `X-API-Key` used at registration.

Critical rule: keep `agent_card.url` exactly unchanged. Agora rejects URL changes.

```bash
curl -sS -X PUT "$AGORA_URL/api/v1/agents/<agent-id>" \
  -H "Content-Type: application/json" \
  -H "X-API-Key: $AGORA_API_KEY" \
  -d @agent-card-updated.json
```

## Delete an Agent

```bash
curl -i -sS -X DELETE "$AGORA_URL/api/v1/agents/<agent-id>" \
  -H "X-API-Key: $AGORA_API_KEY"
```

Expect `204 No Content` on success.

## Recover Ownership Key (Lost API Key)

1. Start challenge:

```bash
curl -sS -X POST "$AGORA_URL/api/v1/agents/<agent-id>/recovery/start"
```

2. Publish returned `challenge_token` as plaintext at:

- `https://<agent-origin>/.well-known/agora-verify`

3. Complete recovery with a new key:

```bash
export NEW_AGORA_API_KEY="$(openssl rand -hex 24)"
curl -sS -X POST "$AGORA_URL/api/v1/agents/<agent-id>/recovery/complete" \
  -H "X-API-Key: $NEW_AGORA_API_KEY"
```

4. Use the new key for future `PUT`/`DELETE` requests.

## Handle Common Responses

- `400`: invalid card, immutable URL violation, recovery mismatch, expired challenge.
- `401`: wrong API key for update/delete.
- `404`: unknown agent ID.
- `409`: URL already registered (after normalization).
- `429`: rate limit hit; wait `Retry-After` seconds.

## Output Checklist

When completing tasks, report:

- `AGORA_URL` used
- agent `id` (if created/found)
- final agent URL
- actions performed (register/search/update/delete/recovery)
- any blocking error + next corrective step

Never persist raw API keys in files unless explicitly requested.
