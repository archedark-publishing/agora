from datetime import datetime, timedelta, timezone

from agora.stale import agent_counts_as_live, compute_stale_metadata


def test_stale_matrix() -> None:
    now = datetime.now(tz=timezone.utc)

    assert compute_stale_metadata(
        health_status="unknown",
        last_healthy_at=None,
        registered_at=now - timedelta(days=30),
        now=now,
    ) == (False, 0)

    assert compute_stale_metadata(
        health_status="healthy",
        last_healthy_at=now - timedelta(days=10),
        registered_at=now - timedelta(days=30),
        now=now,
    ) == (False, 0)

    is_stale, stale_days = compute_stale_metadata(
        health_status="unhealthy",
        last_healthy_at=now - timedelta(days=8),
        registered_at=now - timedelta(days=30),
        now=now,
    )
    assert is_stale is True
    assert stale_days >= 8

    is_stale, stale_days = compute_stale_metadata(
        health_status="unhealthy",
        last_healthy_at=None,
        registered_at=now - timedelta(days=9),
        now=now,
    )
    assert is_stale is True
    assert stale_days >= 9

    assert compute_stale_metadata(
        health_status="unhealthy",
        last_healthy_at=now - timedelta(days=2),
        registered_at=now - timedelta(days=9),
        now=now,
    ) == (False, 0)


def test_counts_as_live_matrix() -> None:
    now = datetime.now(tz=timezone.utc)
    healthy_at = now - timedelta(hours=2)

    # Verified endpoint, passing check → live.
    assert agent_counts_as_live(
        health_status="healthy",
        has_verified_endpoint=True,
        availability=None,
        email_verified=False,
        now=now,
    ) is True

    # Verified endpoint, failing check (regression) → not live.
    assert agent_counts_as_live(
        health_status="unhealthy",
        has_verified_endpoint=True,
        availability=None,
        email_verified=True,
        now=now,
    ) is False

    # Verified endpoint, check never recorded as healthy → not live; only
    # a passing check counts once an endpoint is verified.
    assert agent_counts_as_live(
        health_status="unknown",
        has_verified_endpoint=True,
        availability=None,
        email_verified=True,
        now=now,
    ) is False

    # Never verified, email verified (Tale shape) → live: email
    # verification is the strongest available check.
    assert agent_counts_as_live(
        health_status="unknown",
        has_verified_endpoint=False,
        availability=None,
        email_verified=True,
        now=now,
    ) is True

    # Stale pre-#127 row: "unhealthy" with no proof-of-life timestamp is a
    # mislabeling, not a regression — email verification still counts.
    assert agent_counts_as_live(
        health_status="unhealthy",
        has_verified_endpoint=False,
        availability=None,
        email_verified=True,
        now=now,
    ) is True

    # Never verified, email not verified, fresh heartbeat → live.
    assert agent_counts_as_live(
        health_status="unknown",
        has_verified_endpoint=False,
        availability={"next_active_at": (now + timedelta(hours=1)).isoformat()},
        email_verified=False,
        now=now,
    ) is True

    # Never verified, email not verified, no heartbeat → not live.
    assert agent_counts_as_live(
        health_status="unknown",
        has_verified_endpoint=False,
        availability=None,
        email_verified=False,
        now=now,
    ) is False

    # Never verified, email not verified, expired heartbeat → not live.
    assert agent_counts_as_live(
        health_status="unknown",
        has_verified_endpoint=False,
        availability={"next_active_at": (now - timedelta(hours=1)).isoformat()},
        email_verified=False,
        now=now,
    ) is False
