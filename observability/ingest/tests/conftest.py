"""Shared fixtures for the ingest test suite.

The `write_artifact` factory builds a validated `UpgradeArtifact`,
serializes it through the schema (so tests exercise the same
JSON encoding path the workflow uses), and drops it into an
artifacts directory. Tests get to build whatever shape they need
without duplicating boilerplate per case.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from observability.ingest.schema import Status, UpgradeArtifact

ArtifactFactory = Callable[..., Path]


@pytest.fixture
def artifacts_dir(tmp_path: Path) -> Path:
    d = tmp_path / "artifacts"
    d.mkdir()
    return d


@pytest.fixture
def write_artifact(artifacts_dir: Path) -> ArtifactFactory:
    """Factory that writes one validated artifact to the artifacts dir.

    Sensible defaults so a test can just call write_artifact(device="...")
    when it only cares about the failing piece.
    """

    def _write(
        *,
        wave: str = "canary",
        device: str = "bigip-lab-01",
        status: Status = "success",
        error: str = "",
        start: datetime | None = None,
        end: datetime | None = None,
    ) -> Path:
        start = start or datetime(2026, 4, 24, 18, 0, 0, tzinfo=UTC)
        end = end or start + timedelta(minutes=5)
        art = UpgradeArtifact(
            wave=wave,
            device=device,
            start=start,
            end=end,
            status=status,
            error=error,
        )
        path = artifacts_dir / f"{device}.json"
        path.write_text(art.model_dump_json())
        return path

    return _write


@pytest.fixture
def write_raw_artifact(artifacts_dir: Path) -> Callable[[str, object], Path]:
    """Writes a raw dict/string as an artifact JSON, bypassing the schema.

    Used by malformed-artifact and schema-violation tests to plant
    exactly the bad shape the gate should catch.
    """

    def _write(name: str, payload: object) -> Path:
        path = artifacts_dir / name
        if isinstance(payload, str):
            path.write_text(payload)
        else:
            path.write_text(json.dumps(payload))
        return path

    return _write
