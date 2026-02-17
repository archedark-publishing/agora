#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from dataclasses import dataclass

import httpx


@dataclass(frozen=True)
class SeedAgent:
    api_key: str
    card: dict[str, object]


def build_seed_agents() -> list[SeedAgent]:
    return [
        SeedAgent(
            api_key="seed-weather-key",
            card={
                "protocolVersion": "0.3.0",
                "name": "Weather Watch",
                "description": "Current conditions and 7-day forecasts for major cities.",
                "url": "https://sample.agora.example/weather",
                "version": "1.0.0",
                "capabilities": {"streaming": True},
                "skills": [
                    {
                        "id": "weather-forecast",
                        "name": "Weather Forecast",
                        "description": "Forecast and severe weather lookup.",
                        "tags": ["weather", "forecast", "alerts"],
                        "inputModes": ["application/json"],
                        "outputModes": ["application/json"],
                    }
                ],
                "defaultInputModes": ["application/json"],
                "defaultOutputModes": ["application/json"],
            },
        ),
        SeedAgent(
            api_key="seed-research-key",
            card={
                "protocolVersion": "0.3.0",
                "name": "Research Scout",
                "description": "Finds papers and summarizes key findings by topic.",
                "url": "https://sample.agora.example/research",
                "version": "1.0.0",
                "capabilities": {"streaming": True},
                "skills": [
                    {
                        "id": "paper-search",
                        "name": "Paper Search",
                        "description": "Literature lookup and citation summary.",
                        "tags": ["research", "science", "citations"],
                        "inputModes": ["application/json"],
                        "outputModes": ["application/json"],
                    }
                ],
                "defaultInputModes": ["application/json"],
                "defaultOutputModes": ["application/json"],
            },
        ),
        SeedAgent(
            api_key="seed-code-key",
            card={
                "protocolVersion": "0.3.0",
                "name": "Code Copilot",
                "description": "Generates and reviews code snippets for common tasks.",
                "url": "https://sample.agora.example/code",
                "version": "1.0.0",
                "capabilities": {"streaming": True, "batch": True},
                "skills": [
                    {
                        "id": "code-generation",
                        "name": "Code Generation",
                        "description": "Generate, explain, and refactor code.",
                        "tags": ["code", "programming", "review"],
                        "inputModes": ["application/json"],
                        "outputModes": ["application/json"],
                    }
                ],
                "defaultInputModes": ["application/json"],
                "defaultOutputModes": ["application/json"],
            },
        ),
        SeedAgent(
            api_key="seed-translation-key",
            card={
                "protocolVersion": "0.3.0",
                "name": "Translate Pro",
                "description": "Low-latency translation across major world languages.",
                "url": "https://sample.agora.example/translation",
                "version": "1.0.0",
                "capabilities": {"streaming": True},
                "skills": [
                    {
                        "id": "translation",
                        "name": "Translation",
                        "description": "Translate text while preserving tone.",
                        "tags": ["translation", "localization", "language"],
                        "inputModes": ["application/json"],
                        "outputModes": ["application/json"],
                    }
                ],
                "defaultInputModes": ["application/json"],
                "defaultOutputModes": ["application/json"],
            },
        ),
    ]


def seed_agent(client: httpx.Client, base_url: str, spec: SeedAgent) -> tuple[str, str]:
    try:
        response = client.post(
            f"{base_url.rstrip('/')}/api/v1/agents",
            headers={"X-API-Key": spec.api_key},
            json=spec.card,
        )
    except httpx.HTTPError as exc:
        return ("error", f"request_failed: {exc}")

    if response.status_code == 201:
        data = response.json()
        return ("created", data["id"])

    if response.status_code == 409:
        return ("exists", "duplicate_url")

    detail = response.text
    try:
        detail = json.dumps(response.json(), indent=2)
    except ValueError:
        pass
    return ("error", f"status={response.status_code} detail={detail}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Seed Agora with sample agents")
    parser.add_argument(
        "--base-url",
        default="http://localhost:8000",
        help="Agora API base URL (default: http://localhost:8000)",
    )
    args = parser.parse_args()

    agents = build_seed_agents()
    print(f"Seeding {len(agents)} sample agents into {args.base_url}...")

    with httpx.Client(timeout=10) as client:
        for spec in agents:
            outcome, info = seed_agent(client, args.base_url, spec)
            print(f"- {spec.card['name']}: {outcome} ({info})")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
