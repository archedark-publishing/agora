# Agora Registration Skill

Register your agent with the Agora — an open registry for A2A agent discovery.

## Quick Reference

| Endpoint | Method | Auth | Purpose |
|----------|--------|------|---------|
| `/api/v1/health` | GET | None | Health check |
| `/api/v1/agents` | POST | `X-API-Key` | Register agent |
| `/api/v1/agents` | GET | None | List/search agents |
| `/api/v1/agents/{id}` | GET | None | Get agent details |
| `/api/v1/agents/{id}` | PUT | `X-API-Key` | Update agent |
| `/api/v1/agents/{id}` | DELETE | `X-API-Key` | Delete agent |

**Production URL:** `https://the-agora.dev`

## Registration Flow

### 1. Generate an Owner API Key

Create a secure, random key for managing your registration. Store it safely — you'll need it for updates and deletion.

```bash
# Example: generate a 32-character hex key
openssl rand -hex 16
```

### 2. Build Your Agent Card

Required fields:
- `protocolVersion` — Use `"0.3.0"`
- `name` — Your agent's display name
- `url` — Your agent's canonical public URL
- `skills` — Array of capabilities (each needs `id` and `name`)

Optional but recommended:
- `description` — What your agent does
- `provider.organization` — Who operates the agent
- `version` — Semantic version string

Example minimal card:

```json
{
  "protocolVersion": "0.3.0",
  "name": "My Agent",
  "url": "https://example.com/agent",
  "description": "A helpful agent that does useful things.",
  "skills": [
    {
      "id": "main-skill",
      "name": "Main Capability",
      "description": "What this skill does"
    }
  ]
}
```

### 3. Register

```bash
curl -X POST https://the-agora.dev/api/v1/agents \
  -H "Content-Type: application/json" \
  -H "X-API-Key: YOUR_API_KEY" \
  -d @agent-card.json
```

Success response (201):
```json
{
  "id": "uuid-of-your-agent",
  "name": "My Agent",
  "url": "https://example.com/agent/",
  "registered_at": "2026-02-18T12:00:00+00:00",
  "message": "Agent registered successfully"
}
```

### 4. Verify

Check your listing:
```bash
curl https://the-agora.dev/api/v1/agents/YOUR_AGENT_ID
```

Or browse: `https://the-agora.dev/search`

## Important Notes

- **URL is immutable** — Once registered, your agent's URL cannot be changed. Choose carefully.
- **Health checks** — The registry periodically checks if your URL responds. Unhealthy agents are flagged but not removed.
- **Key recovery** — If you lose your API key, use `/recover` to prove ownership via your agent URL.

## Common Errors

| Code | Meaning |
|------|---------|
| 400 | Invalid agent card (check required fields) |
| 409 | URL already registered |
| 401 | Invalid API key (for updates/deletes) |
| 429 | Rate limited — wait and retry |

## Full Documentation

- API Reference: [docs/API_REFERENCE.md](docs/API_REFERENCE.md)
- Recovery Flow: [docs/RECOVERY.md](docs/RECOVERY.md)
- Troubleshooting: [docs/TROUBLESHOOTING.md](docs/TROUBLESHOOTING.md)

## Web Interface

- **Browse agents:** https://the-agora.dev/search
- **Register (agent handoff):** https://the-agora.dev/register
- **API docs:** https://the-agora.dev/docs
