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
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
alembic upgrade head
uvicorn agora.main:app --reload
```

## Local PostgreSQL Setup (macOS + Linux)

Agora requires PostgreSQL for local development and migrations.

### macOS (Homebrew)

```bash
brew install postgresql@16
brew services start postgresql@16
export PATH="$(brew --prefix)/opt/postgresql@16/bin:$PATH"

createuser -s agora || true
createdb -O agora agora || true
psql -d postgres -c "ALTER USER agora WITH PASSWORD 'password';"

export DATABASE_URL='postgresql+asyncpg://agora:password@localhost:5432/agora'
```

### Linux (Ubuntu/Debian)

These are also a good baseline for deployment on a Linux VM.

```bash
sudo apt update
sudo apt install -y postgresql postgresql-contrib
sudo systemctl enable --now postgresql

sudo -u postgres psql -c "CREATE ROLE agora WITH LOGIN SUPERUSER PASSWORD 'password';" || true
sudo -u postgres createdb -O agora agora || true

export DATABASE_URL='postgresql+asyncpg://agora:password@localhost:5432/agora'
```

### Verify DB + Migrations

```bash
pg_isready -h localhost -p 5432
alembic upgrade head
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
