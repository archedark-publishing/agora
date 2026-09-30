"""Integration tests for the location filter feature.

Covers structured location fields on minimal listings (registration and
update), validation, and the near / country / geo-radius search filters.
"""

from __future__ import annotations

import pytest

import agora.main as main_module


@pytest.fixture
def capture_verification_email(monkeypatch):
    """Capture outbound verification emails instead of sending them."""
    sent: list[dict] = []

    async def _fake_send(*, to_email: str, agent_name: str, verify_url: str) -> bool:
        sent.append(
            {"to_email": to_email, "agent_name": agent_name, "verify_url": verify_url}
        )
        return True

    monkeypatch.setattr(main_module, "_send_verification_email", _fake_send)
    return sent


def _payload(name: str, email: str, **location_fields) -> dict:
    payload = {
        "name": name,
        "description": f"{name} description",
        "email": email,
        "response_sla": "within a day",
        "capabilities": ["plumbing"],
    }
    payload.update(location_fields)
    return payload


async def _register(client, name, email, api_key, **location_fields) -> dict:
    response = await client.post(
        "/api/v1/agents/minimal",
        json=_payload(name, email, **location_fields),
        headers={"X-API-Key": api_key},
    )
    assert response.status_code == 201, response.text
    return response.json()


async def _verify(client, capture_verification_email, email_index=-1) -> None:
    verify_url = capture_verification_email[email_index]["verify_url"]
    assert "token=" in verify_url
    token = verify_url.split("token=", 1)[1]
    response = await client.get(f"/verify-email?token={token}")
    assert response.status_code == 200, response.text


async def _owner_view(client, agent_id, api_key) -> dict:
    response = await client.get(
        f"/api/v1/agents/{agent_id}/minimal",
        headers={"X-API-Key": api_key},
    )
    assert response.status_code == 200, response.text
    return response.json()


# Lansdale PA, Philadelphia PA (~24 mi), New York NY (~70 mi).
LANSDALE = {"city": "Lansdale", "region": "PA", "country_code": "US",
            "latitude": 40.2417, "longitude": -75.2837}
PHILLY = {"city": "Philadelphia", "region": "PA", "country_code": "US",
          "latitude": 39.9526, "longitude": -75.1652}
NYC = {"city": "New York", "region": "NY", "country_code": "US",
       "latitude": 40.7128, "longitude": -74.0060}


async def test_registration_with_structured_location_derives_display(
    client, capture_verification_email
) -> None:
    body = await _register(
        client, "Lansdale Plumber", "plumber@example.com", "loc-key-1", **LANSDALE
    )
    view = await _owner_view(client, body["id"], "loc-key-1")
    assert view["city"] == "Lansdale"
    assert view["region"] == "PA"
    assert view["country_code"] == "US"
    assert view["latitude"] == pytest.approx(40.2417)
    assert view["longitude"] == pytest.approx(-75.2837)
    # No free-text location given: derived from the structured fields.
    assert view["location"] == "Lansdale, PA, US"


async def test_registration_explicit_location_not_overridden(
    client, capture_verification_email
) -> None:
    body = await _register(
        client, "Philly Sparky", "sparky@example.com", "loc-key-2",
        city="Philadelphia", region="PA", country_code="US",
        location="Greater Philadelphia area",
    )
    view = await _owner_view(client, body["id"], "loc-key-2")
    assert view["location"] == "Greater Philadelphia area"
    assert view["city"] == "Philadelphia"


async def test_registration_country_code_case_insensitive(
    client, capture_verification_email
) -> None:
    body = await _register(
        client, "Maple Agent", "maple@example.com", "loc-key-3",
        city="Toronto", country_code="ca",
    )
    view = await _owner_view(client, body["id"], "loc-key-3")
    assert view["country_code"] == "CA"


@pytest.mark.parametrize(
    "fields",
    [
        {"country_code": "XX"},
        {"country_code": "USA"},
        {"latitude": 40.0},
        {"longitude": -75.0},
        {"latitude": 91.0, "longitude": -75.0},
        {"latitude": -91.0, "longitude": -75.0},
        {"latitude": 40.0, "longitude": 181.0},
        {"latitude": "north", "longitude": -75.0},
        {"latitude": True, "longitude": -75.0},
        {"city": "x" * 101},
    ],
)
async def test_registration_location_validation_rejects_bad_input(
    client, capture_verification_email, fields
) -> None:
    response = await client.post(
        "/api/v1/agents/minimal",
        json=_payload("Bad Loc", "badloc@example.com", **fields),
        headers={"X-API-Key": "loc-key-bad"},
    )
    assert response.status_code == 400, response.text


async def test_search_near_filter(client, capture_verification_email) -> None:
    await _register(client, "Lansdale Plumber", "a1@example.com", "k1", **LANSDALE)
    await _register(client, "NYC Plumber", "a2@example.com", "k2", **NYC)
    await _register(client, "Nowhere Agent", "a3@example.com", "k3")
    await _verify(client, capture_verification_email, email_index=0)
    await _verify(client, capture_verification_email, email_index=1)
    await _verify(client, capture_verification_email, email_index=2)

    near = await client.get("/api/v1/agents/search", params={"near": "Lansdale"})
    assert near.status_code == 200
    agents = near.json()["agents"]
    assert [a["name"] for a in agents] == ["Lansdale Plumber"]

    # Region match: only the PA listing.
    region = await client.get("/api/v1/agents/search", params={"near": "PA"})
    assert [a["name"] for a in region.json()["agents"]] == ["Lansdale Plumber"]

    # Country code matches both US listings.
    country = await client.get("/api/v1/agents/search", params={"near": "US"})
    assert {a["name"] for a in country.json()["agents"]} == {
        "Lansdale Plumber",
        "NYC Plumber",
    }

    # Unfiltered search still returns all three.
    all_agents = await client.get("/api/v1/agents/search")
    assert all_agents.json()["total"] == 3


async def test_search_country_filter(client, capture_verification_email) -> None:
    await _register(client, "US Agent", "c1@example.com", "ck1",
                    city="Austin", country_code="US")
    await _register(client, "CA Agent", "c2@example.com", "ck2",
                    city="Toronto", country_code="CA")
    await _verify(client, capture_verification_email, email_index=0)
    await _verify(client, capture_verification_email, email_index=1)

    us = await client.get("/api/v1/agents/search", params={"country": "us"})
    assert [a["name"] for a in us.json()["agents"]] == ["US Agent"]

    bad = await client.get("/api/v1/agents/search", params={"country": "XX"})
    assert bad.status_code == 400


async def test_search_geo_radius(client, capture_verification_email) -> None:
    await _register(client, "Lansdale Plumber", "g1@example.com", "gk1", **LANSDALE)
    await _register(client, "Philly Plumber", "g2@example.com", "gk2", **PHILLY)
    await _register(client, "NYC Plumber", "g3@example.com", "gk3", **NYC)
    await _register(client, "Nowhere Agent", "g4@example.com", "gk4")
    for i in range(4):
        await _verify(client, capture_verification_email, email_index=i)

    params = {"lat": 40.2417, "lon": -75.2837, "radius": 30}
    result = await client.get("/api/v1/agents/search", params=params)
    assert result.status_code == 200
    agents = result.json()["agents"]
    names = [a["name"] for a in agents]
    # Lansdale (~0 mi) and Philly (~24 mi) are inside 30 mi; NYC (~70 mi)
    # and the location-less listing are not.
    assert names == ["Lansdale Plumber", "Philly Plumber"]
    assert agents[0]["distance"] == pytest.approx(0, abs=0.5)
    assert agents[0]["distance_unit"] == "mi"
    assert 20 < agents[1]["distance"] < 30
    for agent in agents:
        assert agent["latitude"] is not None

    # Kilometers: same anchor, 50 km radius catches Philly (~38 km) but not NYC.
    km = await client.get(
        "/api/v1/agents/search",
        params={"lat": 40.2417, "lon": -75.2837, "radius": 50, "radius_unit": "km"},
    )
    km_names = [a["name"] for a in km.json()["agents"]]
    assert km_names == ["Lansdale Plumber", "Philly Plumber"]
    assert km.json()["agents"][0]["distance_unit"] == "km"


async def test_search_geo_requires_both_coordinates(client) -> None:
    lonely = await client.get("/api/v1/agents/search", params={"lat": 40.0})
    assert lonely.status_code == 400


async def test_pending_listing_with_location_stays_hidden(
    client, capture_verification_email
) -> None:
    # Registered but never verified: pending, so invisible on every surface.
    await _register(
        client, "Pending Plumber", "pending@example.com", "pk1", **LANSDALE
    )
    for params in ({"near": "Lansdale"}, {"country": "US"},
                   {"lat": 40.2417, "lon": -75.2837, "radius": 30}):
        result = await client.get("/api/v1/agents/search", params=params)
        assert result.status_code == 200
        assert result.json()["total"] == 0


async def test_update_minimal_listing_location(client, capture_verification_email) -> None:
    body = await _register(
        client, "Wandering Agent", "wander@example.com", "wk1", **LANSDALE
    )
    agent_id = body["id"]

    # Structured change without an explicit display string re-derives it.
    patch = await client.patch(
        f"/api/v1/agents/{agent_id}/minimal",
        json={"city": "Philadelphia"},
        headers={"X-API-Key": "wk1"},
    )
    assert patch.status_code == 200, patch.text
    view = await _owner_view(client, agent_id, "wk1")
    assert view["city"] == "Philadelphia"
    assert view["location"] == "Philadelphia, PA, US"

    # Explicit free-text location wins over derivation.
    patch = await client.patch(
        f"/api/v1/agents/{agent_id}/minimal",
        json={"location": "Serving the Philly suburbs"},
        headers={"X-API-Key": "wk1"},
    )
    assert patch.status_code == 200, patch.text
    view = await _owner_view(client, agent_id, "wk1")
    assert view["location"] == "Serving the Philly suburbs"
    assert view["city"] == "Philadelphia"

    # Clearing structured fields clears the derived display.
    patch = await client.patch(
        f"/api/v1/agents/{agent_id}/minimal",
        json={"city": None, "region": None, "country_code": None,
              "latitude": None, "longitude": None},
        headers={"X-API-Key": "wk1"},
    )
    assert patch.status_code == 200, patch.text
    view = await _owner_view(client, agent_id, "wk1")
    assert view["city"] is None
    assert view["location"] is None

    # One-sided coordinate update is rejected.
    bad = await client.patch(
        f"/api/v1/agents/{agent_id}/minimal",
        json={"latitude": 40.0},
        headers={"X-API-Key": "wk1"},
    )
    assert bad.status_code == 400

    # Unknown fields still rejected.
    unknown = await client.patch(
        f"/api/v1/agents/{agent_id}/minimal",
        json={"street_address": "123 Main St"},
        headers={"X-API-Key": "wk1"},
    )
    assert unknown.status_code == 400


async def test_agents_json_includes_location_fields(
    client, capture_verification_email
) -> None:
    await _register(client, "Lansdale Plumber", "j1@example.com", "jk1", **LANSDALE)
    await _verify(client, capture_verification_email, email_index=0)

    feed = await client.get("/agents.json")
    assert feed.status_code == 200
    agents = feed.json()["agents"]
    assert len(agents) == 1
    agent = agents[0]
    assert agent["city"] == "Lansdale"
    assert agent["region"] == "PA"
    assert agent["country_code"] == "US"
    assert agent["latitude"] == pytest.approx(40.2417)
    assert agent["longitude"] == pytest.approx(-75.2837)
    assert agent["location"] == "Lansdale, PA, US"


async def test_agent_detail_includes_location_fields(
    client, capture_verification_email
) -> None:
    body = await _register(client, "Lansdale Plumber", "d1@example.com", "dk1", **LANSDALE)
    await _verify(client, capture_verification_email, email_index=0)

    detail = await client.get(f"/api/v1/agents/{body['id']}")
    assert detail.status_code == 200
    payload = detail.json()
    assert payload["city"] == "Lansdale"
    assert payload["country_code"] == "US"
    assert payload["latitude"] == pytest.approx(40.2417)
