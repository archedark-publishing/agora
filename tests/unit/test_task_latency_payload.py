from __future__ import annotations

from fastapi import HTTPException

import agora.main as main_module


def test_parse_task_latency_payload_accepts_camel_case_fields() -> None:
    parsed = main_module._parse_task_latency_payload(
        {
            "typicalSeconds": 300,
            "maxSeconds": 600,
            "scheduleBasis": "polling",
            "scheduleExpression": "*/5 * * * *",
        }
    )

    assert parsed == {
        "typicalSeconds": 300,
        "maxSeconds": 600,
        "scheduleBasis": "polling",
        "scheduleExpression": "*/5 * * * *",
    }


def test_parse_task_latency_payload_rejects_unknown_schedule_basis_with_422() -> None:
    try:
        main_module._parse_task_latency_payload(
            {
                "scheduleBasis": "batch",
            }
        )
    except HTTPException as exc:
        assert exc.status_code == 422
        return

    raise AssertionError("Expected HTTPException for invalid scheduleBasis")


def test_extract_task_latency_raw_rejects_conflicting_alias_values() -> None:
    payload = {
        "taskLatency": {"scheduleBasis": "polling"},
        "task_latency": {"scheduleBasis": "webhook"},
    }

    try:
        main_module._extract_task_latency_raw(payload)
    except HTTPException as exc:
        assert exc.status_code == 422
        return

    raise AssertionError("Expected HTTPException when taskLatency and task_latency conflict")
