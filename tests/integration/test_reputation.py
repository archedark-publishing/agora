from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import UUID

import agora.main as main_module
from agora.database import AsyncSessionLocal
from agora.models import Agent, AgentReliabilityReport


def build_payload(name: str, url: str, skill_id: str = "weather") -> dict:
    return {
        "protocolVersion": "0.3.0",
        "name": name,
        "description": f"{name} description",
        "url": url,
        "version": "1.0.0",
        "capabilities": {"streaming": True},
        "skills": [{"id": skill_id, "name": f"{skill_id} skill"}],
    }


async def _register_agent(
    client,
    name: str,
    url: str,
    api_key: str,
    *,
    age_days: int | None = 30,
) -> str:
    response = await client.post(
        "/api/v1/agents",
        json=build_payload(name, url),
        headers={"X-API-Key": api_key},
    )
    assert response.status_code == 201
    agent_id = response.json()["id"]
    if age_days is not None:
        await _set_agent_profile(UUID(agent_id), age_days=age_days)
    return agent_id


async def _set_agent_profile(
    agent_id: UUID,
    *,
    age_days: int,
    healthy: bool = False,
    erc8004_verified: bool = False,
    econ_id: str | None = None,
) -> None:
    async with AsyncSessionLocal() as session:
        agent = await session.get(Agent, agent_id)
        assert agent is not None
        now_utc = datetime.now(tz=timezone.utc)
        agent.registered_at = now_utc - timedelta(days=age_days)
        if healthy:
            agent.health_status = "healthy"
            agent.last_health_check = now_utc
            agent.last_healthy_at = now_utc
        if erc8004_verified:
            agent.erc8004_verified = True
            agent.econ_id = econ_id or "eip155:1:0x1234567890abcdef1234567890abcdef12345678:22"
        await session.commit()


async def _set_report_created_at(report_id: UUID, *, hours_ago: int) -> None:
    async with AsyncSessionLocal() as session:
        report = await session.get(AgentReliabilityReport, report_id)
        assert report is not None
        report.created_at = datetime.now(tz=timezone.utc) - timedelta(hours=hours_ago)
        await session.commit()


async def test_reliability_report_submission_and_score(client) -> None:
    subject_id = await _register_agent(
        client,
        "Subject Agent",
        "https://example.com/subject-agent",
        "subject-key",
    )
    await _register_agent(
        client,
        "Reporter Agent",
        "https://example.com/reporter-agent",
        "reporter-key",
    )

    report = await client.post(
        f"/api/v1/agents/{subject_id}/reliability-reports",
        json={
            "interaction_date": "2026-02-23",
            "response_received": True,
            "response_time_ms": 120,
            "response_valid": True,
            "terms_honored": True,
            "notes": "Reliable and adhered to declared terms.",
        },
        headers={"X-API-Key": "reporter-key"},
    )
    assert report.status_code == 201

    reliability = await client.get(f"/api/v1/agents/{subject_id}/reliability")
    assert reliability.status_code == 200
    body = reliability.json()
    assert body["agent_id"] == subject_id
    assert body["sample_size"] == 1
    assert body["uptime_pct"] == 100.0
    assert body["response_valid_pct"] == 100.0
    assert body["terms_honored_pct"] == 100.0
    assert body["avg_latency_ms"] == 120.0
    assert body["availability_score"] == 100.0


async def test_reliability_report_auth_failure(client) -> None:
    subject_id = await _register_agent(
        client,
        "Subject Agent",
        "https://example.com/reliability-auth-subject",
        "subject-key",
    )

    response = await client.post(
        f"/api/v1/agents/{subject_id}/reliability-reports",
        json={
            "interaction_date": "2026-02-23",
            "response_received": True,
            "response_time_ms": 50,
            "response_valid": True,
            "terms_honored": True,
        },
        headers={"X-API-Key": "not-a-real-key"},
    )
    assert response.status_code == 401


async def test_incident_submission_response_and_combined_reputation(client) -> None:
    subject_id = await _register_agent(
        client,
        "Subject Agent",
        "https://example.com/reputation-subject",
        "subject-key",
    )
    await _register_agent(
        client,
        "Reporter Agent",
        "https://example.com/reputation-reporter",
        "reporter-key",
    )

    incident = await client.post(
        f"/api/v1/agents/{subject_id}/incidents",
        json={
            "category": "deceptive_output",
            "description": "The subject returned contradictory outputs for identical prompts.",
            "outcome": "resolved_poorly",
            "visibility": "public",
        },
        headers={"X-API-Key": "reporter-key"},
    )
    assert incident.status_code == 201
    incident_id = incident.json()["id"]

    response = await client.post(
        f"/api/v1/agents/{subject_id}/incidents/{incident_id}/response",
        json={"response_text": "We identified and fixed the deterministic branching bug."},
        headers={"X-API-Key": "subject-key"},
    )
    assert response.status_code == 200

    reputation = await client.get(f"/api/v1/agents/{subject_id}/reputation")
    assert reputation.status_code == 200
    payload = reputation.json()
    assert payload["incidents"]["total"] == 1
    assert payload["incidents"]["weighted_incident_score"] is not None
    assert payload["incidents"]["by_category"]["deceptive_output"] == 1
    assert payload["incidents"]["response_rate"] == 1.0
    assert payload["reliability"]["sample_size"] == 0
    assert "weighted_reliability_score" in payload["reliability"]


async def test_incident_submission_supports_systematic_under_caution_category(client) -> None:
    subject_id = await _register_agent(
        client,
        "Subject Agent",
        "https://example.com/under-caution-subject",
        "subject-key",
    )
    await _register_agent(
        client,
        "Reporter Agent",
        "https://example.com/under-caution-reporter",
        "reporter-key",
    )

    incident = await client.post(
        f"/api/v1/agents/{subject_id}/incidents",
        json={
            "category": "systematic_under_caution",
            "description": "Subject over-flags safe requests and escalates low-risk prompts repeatedly.",
            "outcome": "ongoing",
            "visibility": "public",
        },
        headers={"X-API-Key": "reporter-key"},
    )
    assert incident.status_code == 201

    reputation = await client.get(f"/api/v1/agents/{subject_id}/reputation")
    assert reputation.status_code == 200
    payload = reputation.json()
    assert payload["incidents"]["by_category"]["systematic_under_caution"] == 1


async def test_incident_category_enum_in_openapi_schema_includes_systematic_under_caution(client) -> None:
    response = await client.get("/openapi.json")
    assert response.status_code == 200

    incident_schema = response.json()["components"]["schemas"]["IncidentCreate"]
    assert (
        "systematic_under_caution"
        in incident_schema["properties"]["category"]["enum"]
    )


async def test_incident_submission_auth_failure(client) -> None:
    subject_id = await _register_agent(
        client,
        "Subject Agent",
        "https://example.com/incident-auth-subject",
        "subject-key",
    )

    response = await client.post(
        f"/api/v1/agents/{subject_id}/incidents",
        json={
            "category": "other",
            "description": "Untrusted reporter should be rejected.",
            "outcome": "unresolved",
            "visibility": "public",
        },
        headers={"X-API-Key": "invalid-key"},
    )
    assert response.status_code == 401


async def test_reputation_submission_rate_limits(client) -> None:
    subject_id = await _register_agent(
        client,
        "Subject Agent",
        "https://example.com/rate-limit-subject",
        "subject-key",
    )
    await _register_agent(
        client,
        "Reporter Agent",
        "https://example.com/rate-limit-reporter",
        "reporter-key",
    )

    for idx in range(10):
        response = await client.post(
            f"/api/v1/agents/{subject_id}/reliability-reports",
            json={
                "interaction_date": "2026-02-23",
                "response_received": True,
                "response_time_ms": 100 + idx,
                "response_valid": True,
                "terms_honored": True,
                "notes": f"report {idx}",
            },
            headers={"X-API-Key": "reporter-key"},
        )
        assert response.status_code == 201

    blocked_reliability = await client.post(
        f"/api/v1/agents/{subject_id}/reliability-reports",
        json={
            "interaction_date": "2026-02-23",
            "response_received": True,
            "response_time_ms": 220,
            "response_valid": True,
            "terms_honored": True,
            "notes": "exceeds limit",
        },
        headers={"X-API-Key": "reporter-key"},
    )
    assert blocked_reliability.status_code == 429

    for _ in range(5):
        response = await client.post(
            f"/api/v1/agents/{subject_id}/incidents",
            json={
                "category": "refusal_to_comply",
                "description": "Weekly limit test incident.",
                "outcome": "unresolved",
                "visibility": "public",
            },
            headers={"X-API-Key": "reporter-key"},
        )
        assert response.status_code == 201

    blocked_incident = await client.post(
        f"/api/v1/agents/{subject_id}/incidents",
        json={
            "category": "refusal_to_comply",
            "description": "A sixth report in one week should be rate limited.",
            "outcome": "unresolved",
            "visibility": "public",
        },
        headers={"X-API-Key": "reporter-key"},
    )
    assert blocked_incident.status_code == 429


async def test_incident_visibility_filters_without_and_with_auth(client) -> None:
    subject_id = await _register_agent(
        client,
        "Subject Agent",
        "https://example.com/visibility-subject",
        "subject-key",
    )
    await _register_agent(
        client,
        "Reporter Agent",
        "https://example.com/visibility-reporter",
        "reporter-key",
    )

    private_incident = await client.post(
        f"/api/v1/agents/{subject_id}/incidents",
        json={
            "category": "data_handling_concern",
            "description": "Private incident for reporter + subject visibility checks.",
            "outcome": "ongoing",
            "visibility": "private",
        },
        headers={"X-API-Key": "reporter-key"},
    )
    assert private_incident.status_code == 201

    public_incident = await client.post(
        f"/api/v1/agents/{subject_id}/incidents",
        json={
            "category": "positive_exceptional_service",
            "description": "Publicly visible positive incident for baseline filtering.",
            "outcome": "resolved_well",
            "visibility": "public",
        },
        headers={"X-API-Key": "subject-key"},
    )
    assert public_incident.status_code == 201

    unauthenticated = await client.get(f"/api/v1/agents/{subject_id}/incidents")
    assert unauthenticated.status_code == 200
    assert unauthenticated.json()["total"] == 1
    assert unauthenticated.json()["incidents"][0]["visibility"] == "public"

    as_reporter = await client.get(
        f"/api/v1/agents/{subject_id}/incidents",
        headers={"X-API-Key": "reporter-key"},
    )
    assert as_reporter.status_code == 200
    assert as_reporter.json()["total"] == 2

    invalid_auth = await client.get(
        f"/api/v1/agents/{subject_id}/incidents",
        headers={"X-API-Key": "bad-key"},
    )
    assert invalid_auth.status_code == 401


async def test_held_reports_hidden_from_public_and_visible_to_admin(client) -> None:
    subject_id = await _register_agent(
        client,
        "Held Subject Agent",
        "https://example.com/held-subject",
        "subject-key",
    )
    await _register_agent(
        client,
        "Held Reporter Agent",
        "https://example.com/held-reporter",
        "reporter-key",
        age_days=0,
    )

    incident = await client.post(
        f"/api/v1/agents/{subject_id}/incidents",
        json={
            "category": "refusal_to_comply",
            "description": "New reporter incident should be held for review window.",
            "outcome": "unresolved",
            "visibility": "public",
        },
        headers={"X-API-Key": "reporter-key"},
    )
    assert incident.status_code == 201
    assert incident.json()["held_until"] is not None

    public_list = await client.get(f"/api/v1/agents/{subject_id}/incidents")
    assert public_list.status_code == 200
    assert public_list.json()["total"] == 0

    previous_admin_token = main_module.settings.admin_api_token
    main_module.settings.admin_api_token = "admin-test-token"
    try:
        admin_list = await client.get(
            "/api/v1/admin/incidents",
            headers={"X-Admin-Token": "admin-test-token"},
        )
    finally:
        main_module.settings.admin_api_token = previous_admin_token

    assert admin_list.status_code == 200
    assert admin_list.json()["total"] == 1
    assert admin_list.json()["incidents"][0]["held_until"] is not None


async def test_reporter_weight_and_weighted_reputation_scores(client) -> None:
    subject_id = await _register_agent(
        client,
        "Weighted Subject Agent",
        "https://example.com/weighted-subject",
        "subject-key",
    )
    established_reporter_id = await _register_agent(
        client,
        "Established Reporter",
        "https://example.com/weighted-established",
        "established-key",
    )
    await _register_agent(
        client,
        "New Reporter",
        "https://example.com/weighted-new",
        "new-key",
        age_days=0,
    )

    await _set_agent_profile(
        UUID(established_reporter_id),
        age_days=45,
        healthy=True,
        erc8004_verified=True,
        econ_id="eip155:10:0x1234567890abcdef1234567890abcdef12345678:1",
    )

    established_report = await client.post(
        f"/api/v1/agents/{subject_id}/reliability-reports",
        json={
            "interaction_date": "2026-03-20",
            "response_received": True,
            "response_time_ms": 90,
            "response_valid": True,
            "terms_honored": True,
        },
        headers={"X-API-Key": "established-key"},
    )
    assert established_report.status_code == 201

    new_report = await client.post(
        f"/api/v1/agents/{subject_id}/reliability-reports",
        json={
            "interaction_date": "2026-03-20",
            "response_received": False,
            "response_valid": False,
            "terms_honored": False,
        },
        headers={"X-API-Key": "new-key"},
    )
    assert new_report.status_code == 201

    assert established_report.json()["reporter_weight"] > new_report.json()["reporter_weight"]

    reputation = await client.get(f"/api/v1/agents/{subject_id}/reputation")
    assert reputation.status_code == 200
    payload = reputation.json()
    assert payload["reliability"]["sample_size"] == 1
    assert payload["reliability"]["weighted_reliability_score"] is not None


async def test_retract_reliability_report_within_window(client) -> None:
    subject_id = await _register_agent(
        client,
        "Retraction Subject Agent",
        "https://example.com/retract-subject",
        "subject-key",
    )
    reporter_id = await _register_agent(
        client,
        "Retraction Reporter Agent",
        "https://example.com/retract-reporter",
        "reporter-key",
    )
    await _set_agent_profile(UUID(reporter_id), age_days=30, healthy=True)

    report = await client.post(
        f"/api/v1/agents/{subject_id}/reliability-reports",
        json={
            "interaction_date": "2026-03-20",
            "response_received": True,
            "response_time_ms": 150,
            "response_valid": True,
            "terms_honored": True,
        },
        headers={"X-API-Key": "reporter-key"},
    )
    assert report.status_code == 201
    report_id = report.json()["id"]

    retract = await client.delete(
        f"/api/v1/agents/{subject_id}/reliability-reports/{report_id}",
        headers={"X-API-Key": "reporter-key"},
    )
    assert retract.status_code == 200
    assert retract.json()["retracted_at"] is not None

    reliability = await client.get(f"/api/v1/agents/{subject_id}/reliability")
    assert reliability.status_code == 200
    assert reliability.json()["sample_size"] == 0


async def test_retract_reliability_report_rejects_after_24h(client) -> None:
    subject_id = await _register_agent(
        client,
        "Retraction Late Subject",
        "https://example.com/retract-late-subject",
        "subject-key",
    )
    reporter_id = await _register_agent(
        client,
        "Retraction Late Reporter",
        "https://example.com/retract-late-reporter",
        "reporter-key",
    )
    await _set_agent_profile(UUID(reporter_id), age_days=30, healthy=True)

    report = await client.post(
        f"/api/v1/agents/{subject_id}/reliability-reports",
        json={
            "interaction_date": "2026-03-20",
            "response_received": True,
            "response_time_ms": 120,
            "response_valid": True,
            "terms_honored": True,
        },
        headers={"X-API-Key": "reporter-key"},
    )
    assert report.status_code == 201
    report_id = UUID(report.json()["id"])

    await _set_report_created_at(report_id, hours_ago=25)

    retract = await client.delete(
        f"/api/v1/agents/{subject_id}/reliability-reports/{report_id}",
        headers={"X-API-Key": "reporter-key"},
    )
    assert retract.status_code == 409


async def test_incident_dispute_endpoint_marks_disputed(client) -> None:
    subject_id = await _register_agent(
        client,
        "Dispute Subject Agent",
        "https://example.com/dispute-subject",
        "subject-key",
    )
    reporter_id = await _register_agent(
        client,
        "Dispute Reporter Agent",
        "https://example.com/dispute-reporter",
        "reporter-key",
    )
    await _set_agent_profile(UUID(reporter_id), age_days=20, healthy=True)

    incident = await client.post(
        f"/api/v1/agents/{subject_id}/incidents",
        json={
            "category": "deceptive_output",
            "description": "Dispute flow coverage incident.",
            "outcome": "ongoing",
            "visibility": "public",
        },
        headers={"X-API-Key": "reporter-key"},
    )
    assert incident.status_code == 201
    incident_id = incident.json()["id"]

    dispute = await client.post(
        f"/api/v1/agents/{subject_id}/incidents/{incident_id}/dispute",
        headers={"X-API-Key": "subject-key"},
    )
    assert dispute.status_code == 200
    assert dispute.json()["disputed"] is True
    assert dispute.json()["disputed_at"] is not None


async def test_anomaly_job_flags_incident_from_reporter_with_no_health_history(client) -> None:
    subject_id = await _register_agent(
        client,
        "Flag Subject Agent",
        "https://example.com/flag-subject",
        "subject-key",
    )
    reporter_id = await _register_agent(
        client,
        "Flag Reporter Agent",
        "https://example.com/flag-reporter",
        "reporter-key",
    )
    await _set_agent_profile(UUID(reporter_id), age_days=21, healthy=False)

    incident = await client.post(
        f"/api/v1/agents/{subject_id}/incidents",
        json={
            "category": "refusal_to_comply",
            "description": "No-health reporter anomaly coverage.",
            "outcome": "unresolved",
            "visibility": "public",
        },
        headers={"X-API-Key": "reporter-key"},
    )
    assert incident.status_code == 201

    async with AsyncSessionLocal() as session:
        await main_module._flag_reputation_anomalies(
            session,
            now_utc=datetime.now(tz=timezone.utc),
        )
        await session.commit()

    previous_admin_token = main_module.settings.admin_api_token
    main_module.settings.admin_api_token = "admin-test-token"
    try:
        admin_incidents = await client.get(
            "/api/v1/admin/incidents",
            headers={"X-Admin-Token": "admin-test-token"},
            params={"flagged_only": "true"},
        )
    finally:
        main_module.settings.admin_api_token = previous_admin_token

    assert admin_incidents.status_code == 200
    assert admin_incidents.json()["total"] >= 1
    assert any(item["flagged_for_review"] for item in admin_incidents.json()["incidents"])
