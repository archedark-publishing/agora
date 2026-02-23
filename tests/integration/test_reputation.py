from __future__ import annotations


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


async def _register_agent(client, name: str, url: str, api_key: str) -> str:
    response = await client.post(
        "/api/v1/agents",
        json=build_payload(name, url),
        headers={"X-API-Key": api_key},
    )
    assert response.status_code == 201
    return response.json()["id"]


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
            "notes": "Reliable and adhered to the declared contract terms.",
        },
        headers={"X-API-Key": "reporter-key"},
    )
    assert report.status_code == 201

    reliability = await client.get(f"/api/v1/agents/{subject_id}/reliability")
    assert reliability.status_code == 200
    body = reliability.json()
    assert body["subject_agent_id"] == subject_id
    assert body["total_reports"] == 1
    assert body["response_rate"] == 1.0
    assert body["validity_rate"] == 1.0
    assert body["terms_honor_rate"] == 1.0


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
            "category": "error_handling",
            "description": (
                "The subject agent returned an inconsistent schema when the upstream service timed out, "
                "then recovered without documenting the behavior in its status response."
            ),
            "outcome": "resolved_poorly",
            "visibility": "public",
        },
        headers={"X-API-Key": "reporter-key"},
    )
    assert incident.status_code == 201
    incident_id = incident.json()["id"]

    incidents = await client.get(f"/api/v1/agents/{subject_id}/incidents")
    assert incidents.status_code == 200
    assert incidents.json()["total"] == 1

    response = await client.post(
        f"/api/v1/agents/{subject_id}/incidents/{incident_id}/response",
        json={"response_text": "We fixed the timeout fallback and deployed stricter schema validation."},
        headers={"X-API-Key": "subject-key"},
    )
    assert response.status_code == 200

    reputation = await client.get(f"/api/v1/agents/{subject_id}/reputation")
    assert reputation.status_code == 200
    payload = reputation.json()
    assert payload["incidents"]["total"] == 1
    assert payload["incidents"]["by_category"]["error_handling"] == 1
    assert payload["incidents"]["response_rate"] == 1.0


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

    for _ in range(3):
        response = await client.post(
            f"/api/v1/agents/{subject_id}/incidents",
            json={
                "category": "refusal",
                "description": (
                    "The reporter observed a refusal path that did not follow the documented contract, "
                    "and the fallback guidance did not provide actionable remediation steps."
                ),
                "outcome": "unresolved",
                "visibility": "public",
            },
            headers={"X-API-Key": "reporter-key"},
        )
        assert response.status_code == 201

    blocked_incident = await client.post(
        f"/api/v1/agents/{subject_id}/incidents",
        json={
            "category": "refusal",
            "description": (
                "A fourth submission in the same UTC day should be rate limited by reporter-subject pair, "
                "matching the acceptance criteria for incident report quotas."
            ),
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
            "category": "disclosure",
            "description": (
                "This private disclosure documents an internal mitigation path where the subject and reporter "
                "coordinated on remediation before public disclosure was appropriate."
            ),
            "outcome": "ongoing",
            "visibility": "private",
        },
        headers={"X-API-Key": "reporter-key"},
    )
    assert private_incident.status_code == 201

    public_incident = await client.post(
        f"/api/v1/agents/{subject_id}/incidents",
        json={
            "category": "resolution",
            "description": (
                "Public incident describing the same chain with enough context for external observers to "
                "understand behavior, remediation, and current confidence level."
            ),
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
