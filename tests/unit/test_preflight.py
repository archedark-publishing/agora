from __future__ import annotations

import httpx

import agora.main as main_module
from agora.main import app


def _payload(
    *,
    name: str = "Preflight Agent",
    url: str = "https://example.com/agents/preflight",
    include_did: bool = False,
    include_commitments: bool = False,
    include_oatr: bool = False,
) -> dict:
    body: dict[str, object] = {
        "protocolVersion": "0.3.0",
        "name": name,
        "description": "Preflight endpoint test agent",
        "url": url,
        "version": "1.0.0",
        "capabilities": {"streaming": True},
        "skills": [{"id": "preflight", "name": "Preflight"}],
    }
    if include_did:
        body["did"] = "did:web:agent.example"
    if include_commitments:
        body["commitments_url"] = "https://agent.example/.well-known/agent-commitments.json"
    if include_oatr:
        body["agent_trust_url"] = "https://agent.example/.well-known/agent-trust.json"
    return body


async def test_preflight_returns_pass_when_all_checks_pass(monkeypatch) -> None:
    async def _health(_url: str) -> dict[str, str | None]:
        return {"status": "pass", "detail": "health ok"}

    async def _did(_did: str | None) -> dict[str, str | None]:
        return {"status": "pass", "detail": "did ok"}

    async def _oatr(_url: str | None) -> dict[str, str | None]:
        return {"status": "pass", "detail": "oatr ok"}

    async def _commitments(**_kwargs) -> dict[str, str | None]:
        return {"status": "pass", "detail": "commitments ok"}

    monkeypatch.setattr(main_module, "_run_preflight_health_check", _health)
    monkeypatch.setattr(main_module, "_run_preflight_did_check", _did)
    monkeypatch.setattr(main_module, "_run_preflight_oatr_check", _oatr)
    monkeypatch.setattr(main_module, "_run_preflight_commitments_check", _commitments)

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.post(
            "/api/v1/agents/preflight",
            json=_payload(include_did=True, include_commitments=True, include_oatr=True),
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["overall"] == "pass"
    assert payload["checks"]["schema"]["status"] == "pass"
    assert payload["checks"]["health"]["status"] == "pass"
    assert payload["checks"]["did"]["status"] == "pass"
    assert payload["checks"]["oatr"]["status"] == "pass"
    assert payload["checks"]["commitments"]["status"] == "pass"


async def test_preflight_schema_failure_returns_overall_fail() -> None:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.post(
            "/api/v1/agents/preflight",
            json={
                "protocolVersion": "0.3.0",
                "name": "Invalid Agent",
                "url": "https://example.com/invalid",
                # missing required `skills`
            },
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["overall"] == "fail"
    assert payload["checks"]["schema"]["status"] == "fail"
    assert payload["checks"]["health"]["status"] == "skip"
    assert payload["checks"]["did"]["status"] == "skip"
    assert payload["checks"]["oatr"]["status"] == "skip"
    assert payload["checks"]["commitments"]["status"] == "skip"


async def test_preflight_health_failure_sets_overall_fail(monkeypatch) -> None:
    async def _health(_url: str) -> dict[str, str | None]:
        return {"status": "fail", "detail": "unreachable"}

    monkeypatch.setattr(main_module, "_run_preflight_health_check", _health)

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.post(
            "/api/v1/agents/preflight",
            json=_payload(),
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["overall"] == "fail"
    assert payload["checks"]["schema"]["status"] == "pass"
    assert payload["checks"]["health"]["status"] == "fail"


async def test_preflight_skips_did_check_when_did_missing(monkeypatch) -> None:
    async def _health(_url: str) -> dict[str, str | None]:
        return {"status": "pass", "detail": "health ok"}

    monkeypatch.setattr(main_module, "_run_preflight_health_check", _health)

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.post(
            "/api/v1/agents/preflight",
            json=_payload(),
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["checks"]["did"]["status"] == "skip"
    assert "did field not provided" in (payload["checks"]["did"]["detail"] or "")


async def test_preflight_skips_commitments_when_url_missing(monkeypatch) -> None:
    async def _health(_url: str) -> dict[str, str | None]:
        return {"status": "pass", "detail": "health ok"}

    async def _did(_did: str | None) -> dict[str, str | None]:
        return {"status": "pass", "detail": "did ok"}

    monkeypatch.setattr(main_module, "_run_preflight_health_check", _health)
    monkeypatch.setattr(main_module, "_run_preflight_did_check", _did)

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.post(
            "/api/v1/agents/preflight",
            json=_payload(include_did=True),
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["checks"]["did"]["status"] == "pass"
    assert payload["checks"]["commitments"]["status"] == "skip"
    assert "commitments_url not provided" in (payload["checks"]["commitments"]["detail"] or "")


async def test_preflight_rejects_malformed_json() -> None:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.post(
            "/api/v1/agents/preflight",
            content='{"bad_json": ',
            headers={"Content-Type": "application/json"},
        )

    assert response.status_code == 400
    assert response.json()["detail"] == "Malformed JSON body"
