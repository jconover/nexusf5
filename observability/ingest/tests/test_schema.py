"""Schema contract tests.

The schema is a load-bearing interface between the workflow (writer)
and Phase 5's dashboard (pusher). These tests pin the contract: the six
fields, the device-hostname pattern, and the `extra="forbid"` policy
that makes drift loud at ingestion.

If any of these tests needs to change, ARCHITECTURE.md and the
dashboard need to change with it — not the other way around.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from observability.ingest.schema import UpgradeArtifact
from pydantic import ValidationError


def _minimal(**overrides: object) -> dict[str, object]:
    base: dict[str, object] = {
        "wave": "canary",
        "device": "bigip-lab-01",
        "start": "2026-04-24T18:00:00Z",
        "end": "2026-04-24T18:05:00Z",
        "status": "success",
        "error": "",
    }
    base.update(overrides)
    return base


def test_happy_construct() -> None:
    art = UpgradeArtifact(**_minimal())  # type: ignore[arg-type]
    assert art.wave == "canary"
    assert art.status == "success"
    assert art.start == datetime(2026, 4, 24, 18, 0, 0, tzinfo=UTC)


def test_extra_field_forbidden() -> None:
    with pytest.raises(ValidationError, match="extra"):
        UpgradeArtifact(**_minimal(target_version="17.1.0"))  # type: ignore[arg-type]


def test_unknown_status_rejected() -> None:
    with pytest.raises(ValidationError):
        UpgradeArtifact(**_minimal(status="mostly ok"))  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "device",
    ["notabigip", "bigip-", "bigip-LAB-01", "bigip-lab-1", "bigip-lab-"],
)
def test_bad_device_pattern_rejected(device: str) -> None:
    with pytest.raises(ValidationError):
        UpgradeArtifact(**_minimal(device=device))  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "device",
    ["bigip-lab-01", "bigip-dc1-042", "bigip-stage-100"],
)
def test_good_device_pattern_accepted(device: str) -> None:
    art = UpgradeArtifact(**_minimal(device=device))  # type: ignore[arg-type]
    assert art.device == device


def test_model_is_frozen() -> None:
    art = UpgradeArtifact(**_minimal())  # type: ignore[arg-type]
    with pytest.raises(ValidationError):
        art.status = "failed"


def test_json_round_trip_stable() -> None:
    art = UpgradeArtifact(**_minimal(status="failed", error="boot timeout"))  # type: ignore[arg-type]
    as_json = art.model_dump_json()
    again = UpgradeArtifact.model_validate_json(as_json)
    assert again == art
