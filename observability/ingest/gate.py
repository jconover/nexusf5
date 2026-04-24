"""Success-rate gate for wave-to-wave promotion.

The reusable workflow calls this as a dedicated job between waves. It
reads every artifact from the prior wave, validates each against the
schema, computes the success rate, and compares to a threshold. Exit 0
promotes; exit 1 blocks.

Failure semantics are deliberate:

- If the prior-wave artifacts directory is missing or empty, this is a
  "we don't know" condition, not a "probably ok" condition. The gate
  **fails closed** — exit 1 — to prevent a partially-run or skipped
  prior wave from silently unlocking the next one. Re-running the prior
  wave is the recovery path; the gate refuses to guess.
- If any artifact fails schema validation (bad JSON, unknown fields,
  missing required fields, malformed timestamps), the gate fails — exit
  1 — and names the offending file. A half-populated artifact set is
  worse than no artifact set; the gate refuses to quietly drop the bad
  one and promote on the rest.
- If every artifact validates and the success rate meets or exceeds the
  threshold, the gate passes — exit 0.
- If every artifact validates and the success rate is below threshold,
  the gate fails — exit 1 — and names the failed devices.

Invocation (wrapper in the workflow job):

    python -m observability.ingest.gate \\
        --prior-wave canary \\
        --artifacts-dir ./canary-artifacts \\
        --threshold 1.0

Exit code drives the GitHub Actions job result.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import TextIO

from observability.ingest.schema import UpgradeArtifact
from pydantic import ValidationError


@dataclass(frozen=True)
class GateOutcome:
    """Structured result of a gate evaluation.

    Kept separate from the CLI so tests can assert on fields directly
    without parsing argparse output or mocking sys.exit. The CLI is a
    thin wrapper that translates this into an exit code + stderr msg.
    """

    passed: bool
    reason: str
    total: int = 0
    succeeded: int = 0
    failed_devices: tuple[str, ...] = ()


def evaluate(
    *,
    artifacts_dir: Path,
    threshold: float,
) -> GateOutcome:
    """Evaluate the gate. Pure function — no I/O beyond reading the dir.

    Threshold is the minimum success rate (0.0 to 1.0) required to pass.
    1.0 means every device succeeded (canary's default). 0.95 would
    tolerate up to 5% device failures.
    """

    if not artifacts_dir.exists():
        return GateOutcome(
            passed=False,
            reason=(
                f"prior-wave artifacts directory not found: {artifacts_dir}. "
                "Gate fails closed — re-run the prior wave before promoting."
            ),
        )

    files = sorted(artifacts_dir.glob("*.json"))
    if not files:
        return GateOutcome(
            passed=False,
            reason=(
                f"no artifacts found in {artifacts_dir}. Gate fails closed — "
                "an empty artifact set is not a success, it's a missing run."
            ),
        )

    artifacts: list[UpgradeArtifact] = []
    for path in files:
        try:
            raw = json.loads(path.read_text())
        except json.JSONDecodeError as exc:
            return GateOutcome(
                passed=False,
                reason=f"malformed JSON in {path.name}: {exc.msg} (line {exc.lineno}).",
            )
        try:
            artifacts.append(UpgradeArtifact.model_validate(raw))
        except ValidationError as exc:
            # Single-line summary for the CLI log; full error is in
            # the structured output for anyone parsing stderr.
            first = exc.errors()[0]
            loc = ".".join(str(p) for p in first["loc"]) or "<root>"
            return GateOutcome(
                passed=False,
                reason=(f"schema violation in {path.name}: {loc}: {first['msg']}"),
            )

    total = len(artifacts)
    succeeded = sum(1 for a in artifacts if a.status == "success")
    failed_devices = tuple(a.device for a in artifacts if a.status != "success")
    rate = succeeded / total

    if rate + 1e-9 < threshold:  # tiny float-slack for boundary cases
        return GateOutcome(
            passed=False,
            reason=(
                f"success rate {succeeded}/{total} ({rate:.1%}) below "
                f"threshold {threshold:.1%}. Failed devices: "
                f"{', '.join(failed_devices)}."
            ),
            total=total,
            succeeded=succeeded,
            failed_devices=failed_devices,
        )

    return GateOutcome(
        passed=True,
        reason=f"success rate {succeeded}/{total} ({rate:.1%}) meets threshold {threshold:.1%}.",
        total=total,
        succeeded=succeeded,
        failed_devices=failed_devices,
    )


def _parse_args(argv: list[str]) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        prog="observability.ingest.gate",
        description="Success-rate gate between wave runs.",
    )
    p.add_argument(
        "--prior-wave",
        required=True,
        help="Name of the wave whose artifacts are being evaluated (for logging).",
    )
    p.add_argument(
        "--artifacts-dir",
        required=True,
        type=Path,
        help="Directory containing the prior wave's *.json artifacts.",
    )
    p.add_argument(
        "--threshold",
        type=float,
        default=1.0,
        help="Minimum success rate to pass (0.0-1.0). Default 1.0 = every device.",
    )
    return p.parse_args(argv)


def main(argv: list[str] | None = None, *, stdout: TextIO = sys.stdout) -> int:
    args = _parse_args(argv if argv is not None else sys.argv[1:])
    outcome = evaluate(
        artifacts_dir=args.artifacts_dir,
        threshold=args.threshold,
    )
    prefix = "gate-pass" if outcome.passed else "gate-fail"
    print(f"[{prefix}] wave={args.prior_wave}: {outcome.reason}", file=stdout)
    return 0 if outcome.passed else 1


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
