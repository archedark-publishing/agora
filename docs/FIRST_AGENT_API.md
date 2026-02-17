# First Agent API Walkthrough

This walkthrough covers the complete lifecycle:

1. register
2. search
3. detail
4. update
5. delete

## Base Setup

```bash
export AGORA_URL="http://localhost:8000"
export API_KEY="demo-owner-key"
```

## 1) Register an Agent

Create an agent card payload:

```bash
cat > /tmp/agent-card.json <<'JSON'
{
  "protocolVersion": "0.3.0",
  "name": "Demo Weather Agent",
  "description": "Returns weather summaries for requested cities.",
  "url": "https://example.com/agents/weather",
  "version": "1.0.0",
  "capabilities": {
    "streaming": true
  },
  "skills": [
    {
      "id": "weather-forecast",
      "name": "Weather Forecast",
      "description": "Current weather and 7-day forecast.",
      "tags": ["weather", "forecast"],
      "inputModes": ["application/json"],
      "outputModes": ["application/json"]
    }
  ],
  "defaultInputModes": ["application/json"],
  "defaultOutputModes": ["application/json"]
}
JSON
```

Register:

```bash
REGISTER_RESPONSE=$(curl -sS -X POST "$AGORA_URL/api/v1/agents" \
  -H "Content-Type: application/json" \
  -H "X-API-Key: $API_KEY" \
  -d @/tmp/agent-card.json)

echo "$REGISTER_RESPONSE"
```

Extract ID:

```bash
AGENT_ID=$(echo "$REGISTER_RESPONSE" | python -c 'import json,sys; print(json.load(sys.stdin)["id"])')
echo "$AGENT_ID"
```

## 2) Search

```bash
curl -sS "$AGORA_URL/api/v1/agents?skill=weather-forecast&limit=20&offset=0"
```

## 3) Fetch Agent Detail

```bash
curl -sS "$AGORA_URL/api/v1/agents/$AGENT_ID"
```

## 4) Update Agent

Important: `url` is immutable and must stay identical.

```bash
cat > /tmp/agent-card-updated.json <<'JSON'
{
  "protocolVersion": "0.3.0",
  "name": "Demo Weather Agent v2",
  "description": "Returns weather summaries and severe-weather alerts.",
  "url": "https://example.com/agents/weather",
  "version": "1.1.0",
  "capabilities": {
    "streaming": true,
    "batch": true
  },
  "skills": [
    {
      "id": "weather-forecast",
      "name": "Weather Forecast",
      "description": "Current weather and 7-day forecast.",
      "tags": ["weather", "forecast", "alerts"],
      "inputModes": ["application/json"],
      "outputModes": ["application/json"]
    }
  ],
  "defaultInputModes": ["application/json"],
  "defaultOutputModes": ["application/json"]
}
JSON
```

```bash
curl -sS -X PUT "$AGORA_URL/api/v1/agents/$AGENT_ID" \
  -H "Content-Type: application/json" \
  -H "X-API-Key: $API_KEY" \
  -d @/tmp/agent-card-updated.json
```

## 5) Delete Agent

```bash
curl -sS -X DELETE "$AGORA_URL/api/v1/agents/$AGENT_ID" \
  -H "X-API-Key: $API_KEY" \
  -i
```

Expected status: `204 No Content`.

## Common API Errors

- `400 Invalid Agent Card`: payload shape or fields are invalid.
- `400 Agent URL is immutable`: update attempted with a changed URL.
- `401 Invalid API key`: wrong owner key for update/delete.
- `409 Agent with this URL already exists`: duplicate normalized URL.
- `429 Rate limit exceeded`: retry after `Retry-After` seconds.
