"""Artifact schema for per-device wave upgrade records.

The six fields here are the load-bearing interface between Phase 3's
workflows (which write artifacts) and Phase 5's Grafana dashboard
(which reads them via Pushgateway). ARCHITECTURE.md fixes the field
set: {wave, device, start, end, status, error}. Do not add fields
here without updating ARCHITECTURE.md and the dashboard together —
Phase 5 is built around this shape, not the other way around.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

Status = Literal["success", "failed"]


class UpgradeArtifact(BaseModel):
    """One per device per wave run. Emitted by the workflow via writer.py,
    consumed by gate.py (success-rate) and pusher.py (Pushgateway metrics)."""

    model_config = ConfigDict(
        # Freeze the shape: unknown fields are a drift signal, not a
        # silent-ignore. If the workflow emits a field the model doesn't
        # know about, fail loudly so it's caught at ingestion, not in
        # whatever downstream panel stops updating silently.
        extra="forbid",
        frozen=True,
    )

    wave: str = Field(
        ...,
        min_length=1,
        description="Wave group name: canary / wave_1 / wave_2 / wave_3.",
    )
    device: str = Field(
        ...,
        min_length=1,
        pattern=r"^bigip-[a-z0-9]+-\d{2,}$",
        description="Device inventory hostname, e.g. bigip-lab-07.",
    )
    start: datetime = Field(
        ...,
        description="Upgrade start time (UTC, ISO 8601).",
    )
    end: datetime = Field(
        ...,
        description="Upgrade end time (UTC, ISO 8601). May equal start on instant failures.",
    )
    status: Status = Field(
        ...,
        description="Terminal status. Anything other than 'success' is a failed device.",
    )
    error: str = Field(
        default="",
        description=(
            "Failure summary when status != success. Empty string on success; "
            "a non-empty error on success is flagged as a schema inconsistency."
        ),
    )
