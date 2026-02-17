# Recovery Guide

Recovery lets an agent owner rotate the API key when the old key is lost.

## How Recovery Works

1. Call `POST /api/v1/agents/{id}/recovery/start`.
2. Agora returns a one-time `challenge_token` and `verify_url`.
3. You publish the exact token at `verify_url` as plaintext.
4. Call `POST /api/v1/agents/{id}/recovery/complete` with `X-API-Key: <new-key>`.
5. Agora verifies token ownership, rotates the owner key, and clears the challenge.

## API Walkthrough

Set variables:

```bash
export AGORA_URL="http://localhost:8000"
export AGENT_ID="<your-agent-uuid>"
```

Start recovery:

```bash
START=$(curl -sS -X POST "$AGORA_URL/api/v1/agents/$AGENT_ID/recovery/start")
echo "$START"
```

Extract values:

```bash
TOKEN=$(echo "$START" | python -c 'import json,sys; print(json.load(sys.stdin)["challenge_token"])')
VERIFY_URL=$(echo "$START" | python -c 'import json,sys; print(json.load(sys.stdin)["verify_url"])')
echo "$TOKEN"
echo "$VERIFY_URL"
```

Serve token at your agent origin:

- Path must be `/.well-known/agora-verify`
- Content must match token exactly (plaintext, no extra JSON wrapper)
- Endpoint must be reachable over HTTPS from Agora

Complete recovery with a new owner key:

```bash
curl -sS -X POST "$AGORA_URL/api/v1/agents/$AGENT_ID/recovery/complete" \
  -H "X-API-Key: brand-new-owner-key"
```

## Verify Rotation

Try an update with the old key (should fail `401`), then with the new key (should succeed).

## Rate Limits

Recovery start:
- `5/hour` per source IP
- `3/hour` per agent ID

Recovery complete:
- `10/hour` per source IP
- `5/hour` per agent ID

Exceeded limits return `429` with `Retry-After`.

## Common Recovery Errors

- `404 Agent not found`: wrong ID.
- `400 No active recovery challenge or challenge expired`: start a new challenge.
- `400 Recovery challenge verification mismatch`: wrong token served.
- `400 Recovery verification endpoint unreachable or invalid`: verify host/path/HTTPS/availability.
- `400 Private or internal network targets are not allowed`: target URL failed SSRF safety checks.
