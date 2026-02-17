from datetime import datetime, timedelta, timezone

from agora.stale import compute_stale_metadata


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
