"""Push validated artifacts to a Prometheus Pushgateway.

The reusable workflow runs this as a final step after the matrix
completes. Every artifact is re-validated against the schema (same
`UpgradeArtifact` model as the gate) before any metric is emitted — a
malformed artifact fails the push job rather than landing a broken
half-set in Pushgateway where the dashboard would show something
nonsensical.

Metrics emitted (Phase 5's Grafana dashboard is built against these —
additions require updating the dashboard and ARCHITECTURE.md together):

- `nexusf5_upgrade_total{wave, status}` (counter): per-wave, per-status
  device count for this run. A wave with 5 devices that all passed
  emits `nexusf5_upgrade_total{wave="canary", status="success"} 5`.
- `nexusf5_upgrade_duration_seconds{wave, device}` (gauge): per-device
  wall time, derived from artifact.end - artifact.start. Not a schema
  field — a projection.

Invocation:

    python -m observability.ingest.pusher \\
        --artifacts-dir ./artifacts \\
        --pushgateway-url https://pushgateway.example.net \\
        --job nexusf5_wave_upgrade \\
        --wave canary

`PUSHGATEWAY_URL` env var is honored as a fallback so the workflow can
source from secrets without having to plumb it through an arg.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
from collections.abc import Iterable
from pathlib import Path
from typing import TextIO

from observability.ingest.schema import UpgradeArtifact
from prometheus_client import CollectorRegistry, Counter, Gauge, push_to_gateway
from pydantic import ValidationError


def _load_artifacts(artifacts_dir: Path) -> list[UpgradeArtifact]:
    files = sorted(artifacts_dir.glob("*.json"))
    artifacts: list[UpgradeArtifact] = []
    for path in files:
        raw = json.loads(path.read_text())
        try:
            artifacts.append(UpgradeArtifact.model_validate(raw))
        except ValidationError as exc:
            raise ValueError(f"schema violation in {path.name}: {exc}") from exc
    return artifacts


def _build_registry(artifacts: Iterable[UpgradeArtifact]) -> CollectorRegistry:
    registry = CollectorRegistry()
    totals = Counter(
        "nexusf5_upgrade_total",
        "Number of device upgrades in this run, by wave and status.",
        labelnames=("wave", "status"),
        registry=registry,
    )
    duration = Gauge(
        "nexusf5_upgrade_duration_seconds",
        "Per-device wall time for this run's upgrade.",
        labelnames=("wave", "device"),
        registry=registry,
    )
    for a in artifacts:
        totals.labels(a.wave, a.status).inc()
        duration.labels(a.wave, a.device).set((a.end - a.start).total_seconds())
    return registry


def push(
    *,
    artifacts_dir: Path,
    pushgateway_url: str,
    job: str,
    wave: str,
) -> int:
    artifacts = _load_artifacts(artifacts_dir)
    if not artifacts:
        # Refuse to push an empty metric set — same fail-closed posture
        # as the gate. An empty push would silently zero the dashboard.
        raise ValueError(f"no artifacts to push from {artifacts_dir}")
    registry = _build_registry(artifacts)
    push_to_gateway(
        pushgateway_url,
        job=job,
        grouping_key={"wave": wave},
        registry=registry,
    )
    return len(artifacts)


def _parse_args(argv: list[str]) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        prog="observability.ingest.pusher",
        description="Validate artifacts and push metrics to a Prometheus Pushgateway.",
    )
    p.add_argument("--artifacts-dir", required=True, type=Path)
    p.add_argument(
        "--pushgateway-url",
        default=os.environ.get("PUSHGATEWAY_URL"),
        help="Base URL. Falls back to $PUSHGATEWAY_URL.",
    )
    p.add_argument("--job", required=True)
    p.add_argument("--wave", required=True)
    return p.parse_args(argv)


def main(argv: list[str] | None = None, *, stdout: TextIO = sys.stdout) -> int:
    args = _parse_args(argv if argv is not None else sys.argv[1:])
    if not args.pushgateway_url:
        print(
            "[pusher-fail] PUSHGATEWAY_URL not set (pass --pushgateway-url or export env).",
            file=stdout,
        )
        return 1
    try:
        count = push(
            artifacts_dir=args.artifacts_dir,
            pushgateway_url=args.pushgateway_url,
            job=args.job,
            wave=args.wave,
        )
    except (ValueError, json.JSONDecodeError, urllib.error.URLError, OSError) as exc:
        print(f"[pusher-fail] {exc}", file=stdout)
        return 1
    print(
        f"[pusher-ok] pushed {count} artifact(s) to {args.pushgateway_url} "
        f"as job={args.job} wave={args.wave}",
        file=stdout,
    )
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
