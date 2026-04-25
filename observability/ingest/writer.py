"""Validated artifact writer, called from the workflow matrix.

Each per-device job in the reusable workflow invokes this to emit its
artifact JSON. Using a Python writer (rather than inline `jq` / heredoc
in bash) means the schema validates at write time, so a field rename or
a stray typo fails the job immediately instead of silently producing a
malformed artifact the gate would reject several minutes later.

Invocation:

    python -m observability.ingest.writer \\
        --wave canary \\
        --device bigip-lab-01 \\
        --start 2026-04-24T18:00:00Z \\
        --end 2026-04-24T18:05:17Z \\
        --status success \\
        --out ./artifacts/bigip-lab-01.json

`--error` is optional; defaults to "" on success. The status value must
be one of `success` / `failed` — the workflow maps GitHub's step outcome
(success/failure/cancelled) onto this before calling.
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime
from pathlib import Path
from typing import TextIO, get_args

from observability.ingest.schema import Status, UpgradeArtifact
from pydantic import ValidationError


def _parse_args(argv: list[str]) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        prog="observability.ingest.writer",
        description="Emit a validated wave-upgrade artifact JSON.",
    )
    p.add_argument("--wave", required=True)
    p.add_argument("--device", required=True)
    p.add_argument("--start", required=True, help="ISO 8601, e.g. 2026-04-24T18:00:00Z")
    p.add_argument("--end", required=True, help="ISO 8601")
    p.add_argument("--status", required=True, choices=list(get_args(Status)))
    p.add_argument("--error", default="", help="Failure summary; empty on success.")
    p.add_argument(
        "--out",
        required=True,
        type=Path,
        help="Path to write artifact JSON. Parent dir must exist.",
    )
    return p.parse_args(argv)


def main(argv: list[str] | None = None, *, stdout: TextIO = sys.stdout) -> int:
    args = _parse_args(argv if argv is not None else sys.argv[1:])
    try:
        art = UpgradeArtifact(
            wave=args.wave,
            device=args.device,
            start=datetime.fromisoformat(args.start.replace("Z", "+00:00")),
            end=datetime.fromisoformat(args.end.replace("Z", "+00:00")),
            status=args.status,
            error=args.error,
        )
    except (ValidationError, ValueError) as exc:
        print(f"[writer-fail] schema validation: {exc}", file=stdout)
        return 1

    args.out.write_text(art.model_dump_json())
    print(f"[writer-ok] {args.device} -> {args.out}", file=stdout)
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
