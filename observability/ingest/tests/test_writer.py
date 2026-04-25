"""Writer tests.

The writer is the first schema-validation checkpoint (before an artifact
hits disk). Tests ensure:

- A well-formed invocation produces a file that the gate then validates
  cleanly — writer and gate share the same schema, so round-tripping
  writer→gate proves they agree.
- Schema-violating arguments (bad device pattern, bad status, bad
  timestamp) fail the writer with a non-zero exit code. The workflow
  would see this and fail the step, stopping the artifact from ever
  reaching upload/Pushgateway/gate.
"""

from __future__ import annotations

import io
import json
from pathlib import Path

from observability.ingest.gate import evaluate
from observability.ingest.writer import main as writer_main


def test_writer_emits_valid_json_gate_accepts(artifacts_dir: Path) -> None:
    out = artifacts_dir / "bigip-lab-07.json"
    rc = writer_main(
        [
            "--wave",
            "wave_1",
            "--device",
            "bigip-lab-07",
            "--start",
            "2026-04-24T18:00:00Z",
            "--end",
            "2026-04-24T18:05:00Z",
            "--status",
            "success",
            "--out",
            str(out),
        ],
        stdout=io.StringIO(),
    )
    assert rc == 0
    assert out.exists()
    payload = json.loads(out.read_text())
    assert payload["device"] == "bigip-lab-07"
    assert payload["status"] == "success"

    # Round-trip: gate accepts what the writer produced.
    outcome = evaluate(artifacts_dir=artifacts_dir, threshold=1.0)
    assert outcome.passed is True


def test_writer_rejects_bad_device_pattern(artifacts_dir: Path) -> None:
    out = artifacts_dir / "bad.json"
    buf = io.StringIO()
    rc = writer_main(
        [
            "--wave",
            "wave_1",
            "--device",
            "not-a-bigip",
            "--start",
            "2026-04-24T18:00:00Z",
            "--end",
            "2026-04-24T18:05:00Z",
            "--status",
            "success",
            "--out",
            str(out),
        ],
        stdout=buf,
    )
    assert rc == 1
    assert not out.exists()
    assert "[writer-fail]" in buf.getvalue()


def test_writer_rejects_bad_timestamp(artifacts_dir: Path) -> None:
    out = artifacts_dir / "bad.json"
    buf = io.StringIO()
    rc = writer_main(
        [
            "--wave",
            "wave_1",
            "--device",
            "bigip-lab-07",
            "--start",
            "not-a-timestamp",
            "--end",
            "2026-04-24T18:05:00Z",
            "--status",
            "success",
            "--out",
            str(out),
        ],
        stdout=buf,
    )
    assert rc == 1
    assert not out.exists()


def test_writer_accepts_failed_with_error_message(artifacts_dir: Path) -> None:
    out = artifacts_dir / "bigip-lab-07.json"
    rc = writer_main(
        [
            "--wave",
            "wave_1",
            "--device",
            "bigip-lab-07",
            "--start",
            "2026-04-24T18:00:00Z",
            "--end",
            "2026-04-24T18:02:12Z",
            "--status",
            "failed",
            "--error",
            "Install to HD1.2 ended with status=failed",
            "--out",
            str(out),
        ],
        stdout=io.StringIO(),
    )
    assert rc == 0
    payload = json.loads(out.read_text())
    assert payload["status"] == "failed"
    assert "status=failed" in payload["error"]
