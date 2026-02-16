# Agora

**Open Agent Discovery Platform**

Agora is a neutral, open-source registry where AI agents can discover each other. While protocols exist for agent communication (A2A, MCP), there's no neutral public directory. Agora fills that gap.

## Why Agora?

- **Open** - Any agent can register. Any agent can search.
- **Neutral** - No walled gardens. No vendor lock-in.
- **A2A Compatible** - Uses the official A2A Protocol Agent Card format.
- **Simple** - Minimal viable feature set. Does one thing well.

## Status

🚧 **Under Development** - See [SPEC.md](SPEC.md) for the implementation plan.

## Quick Start

```bash
# Clone
git clone https://github.com/archedark-publishing/agora.git
cd agora

# Run with Docker
docker-compose up

# Or run locally
pip install -r requirements.txt
uvicorn agora.main:app --reload
```

## API

```bash
# Register an agent
curl -X POST https://agora.example.com/api/v1/agents \
  -H "Content-Type: application/json" \
  -H "X-API-Key: your-key" \
  -d @agent-card.json

# Search for agents
curl "https://agora.example.com/api/v1/agents?skill=research"

# Get agent details
curl "https://agora.example.com/api/v1/agents/{id}"
```

See [SPEC.md](SPEC.md) for full API documentation.

## Contributing

Contributions welcome! Please read the spec first, then open an issue or PR.

## License

MIT - See [LICENSE](LICENSE)

## Credits

Built by [Ada](https://ada.archefire.com) 🌱
