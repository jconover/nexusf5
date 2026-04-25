"""Success-rate gate tests.

Load-bearing: Phase 3's "wave-N gated on wave-N-minus-1" claim is
whatever this file says it is. Each failure mode in the gate's
docstring gets at least one test here, and the pass path gets a
boundary-case test so the threshold-comparison math can't drift.

Structure: one section per failure mode, pass-path at the bottom.
Tests assert on `GateOutcome` (the structured return) AND on `main()`'s
exit code + stderr tag, because the workflow will read both — the
exit code drives the job result, the tag helps an operator skimming
the log figure out which side of the gate they're on.
"""

from __future__ import annotations

import dataclasses
import io
from collections.abc import Callable
from pathlib import Path

import pytest
from observability.ingest.gate import GateOutcome, evaluate, main

ArtifactFactory = Callable[..., Path]


# ---------------------------------------------------------------------------
# Happy path + boundary
# ---------------------------------------------------------------------------


def test_all_success_passes_at_default_threshold(
    write_artifact: ArtifactFactory, artifacts_dir: Path
) -> None:
    for i in range(1, 6):
        write_artifact(device=f"bigip-lab-{i:02d}", status="success")

    outcome = evaluate(artifacts_dir=artifacts_dir, threshold=1.0)

    assert outcome.passed is True
    assert outcome.total == 5
    assert outcome.succeeded == 5
    assert outcome.failed_devices == ()
    assert "5/5" in outcome.reason


def test_exactly_at_threshold_passes(write_artifact: ArtifactFactory, artifacts_dir: Path) -> None:
    # 4/5 = 0.80, threshold = 0.80 → pass (>= comparison).
    for i in range(1, 5):
        write_artifact(device=f"bigip-lab-{i:02d}", status="success")
    write_artifact(device="bigip-lab-05", status="failed", error="boot-switch timeout")

    outcome = evaluate(artifacts_dir=artifacts_dir, threshold=0.80)

    assert outcome.passed is True
    assert outcome.total == 5
    assert outcome.succeeded == 4
    assert outcome.failed_devices == ("bigip-lab-05",)


def test_just_below_threshold_fails(write_artifact: ArtifactFactory, artifacts_dir: Path) -> None:
    # 3/5 = 0.60, threshold = 0.80 → fail.
    for i in range(1, 4):
        write_artifact(device=f"bigip-lab-{i:02d}", status="success")
    for i in range(4, 6):
        write_artifact(device=f"bigip-lab-{i:02d}", status="failed")

    outcome = evaluate(artifacts_dir=artifacts_dir, threshold=0.80)

    assert outcome.passed is False
    assert outcome.succeeded == 3
    assert set(outcome.failed_devices) == {"bigip-lab-04", "bigip-lab-05"}
    # Error message names every failed device — an operator reading the
    # CI log should see the devices to investigate without needing to
    # re-download artifacts.
    for d in outcome.failed_devices:
        assert d in outcome.reason


def test_single_failure_blocks_strict_gate(
    write_artifact: ArtifactFactory, artifacts_dir: Path
) -> None:
    # Canary's default threshold is 1.0 — every device must succeed.
    # One failure out of five blocks promotion. This is the
    # canary→wave_1 gate's most important behavior.
    for i in range(1, 5):
        write_artifact(device=f"bigip-lab-{i:02d}", status="success")
    write_artifact(device="bigip-lab-05", status="failed", error="install failed")

    outcome = evaluate(artifacts_dir=artifacts_dir, threshold=1.0)

    assert outcome.passed is False
    assert outcome.failed_devices == ("bigip-lab-05",)
    assert "below threshold" in outcome.reason


# ---------------------------------------------------------------------------
# Fail-closed on missing / empty prior-wave artifacts
# ---------------------------------------------------------------------------


def test_missing_artifacts_dir_fails_closed(tmp_path: Path) -> None:
    # Gate must NOT treat a missing directory as "assume success."
    # This is the nightmare scenario: prior wave didn't run or its
    # artifacts failed to upload, and the next wave auto-promotes.
    nonexistent = tmp_path / "this-dir-does-not-exist"

    outcome = evaluate(artifacts_dir=nonexistent, threshold=1.0)

    assert outcome.passed is False
    assert "not found" in outcome.reason
    assert "fails closed" in outcome.reason


def test_empty_artifacts_dir_fails_closed(artifacts_dir: Path) -> None:
    # Directory exists but has no JSON files. Same failure class as
    # missing-dir: we don't know if the prior wave ran, so don't promote.
    outcome = evaluate(artifacts_dir=artifacts_dir, threshold=1.0)

    assert outcome.passed is False
    assert "no artifacts" in outcome.reason
    assert "fails closed" in outcome.reason


def test_non_json_files_are_ignored_but_empty_json_set_still_fails(
    artifacts_dir: Path,
) -> None:
    # Unrelated files in the dir (logs, READMEs) do not count as
    # artifacts. If no *.json is present, still fails closed.
    (artifacts_dir / "run.log").write_text("workflow ran here\n")
    (artifacts_dir / "README.md").write_text("# notes\n")

    outcome = evaluate(artifacts_dir=artifacts_dir, threshold=1.0)

    assert outcome.passed is False
    assert "no artifacts" in outcome.reason


# ---------------------------------------------------------------------------
# Malformed / invalid artifacts
# ---------------------------------------------------------------------------


def test_malformed_json_fails_and_names_file(
    write_artifact: ArtifactFactory,
    write_raw_artifact: Callable[[str, object], Path],
    artifacts_dir: Path,
) -> None:
    write_artifact(device="bigip-lab-01", status="success")
    write_raw_artifact("bigip-lab-02.json", "{ this is not valid json")

    outcome = evaluate(artifacts_dir=artifacts_dir, threshold=1.0)

    assert outcome.passed is False
    assert "bigip-lab-02.json" in outcome.reason
    assert "malformed JSON" in outcome.reason


def test_schema_violation_missing_field_fails_and_names_file(
    write_raw_artifact: Callable[[str, object], Path],
    artifacts_dir: Path,
) -> None:
    # Missing `status`. Gate must not silently treat this as a success.
    write_raw_artifact(
        "bigip-lab-01.json",
        {
            "wave": "canary",
            "device": "bigip-lab-01",
            "start": "2026-04-24T18:00:00Z",
            "end": "2026-04-24T18:05:00Z",
            "error": "",
        },
    )

    outcome = evaluate(artifacts_dir=artifacts_dir, threshold=1.0)

    assert outcome.passed is False
    assert "bigip-lab-01.json" in outcome.reason
    assert "schema violation" in outcome.reason


def test_schema_violation_unknown_field_fails_and_names_file(
    write_raw_artifact: Callable[[str, object], Path],
    artifacts_dir: Path,
) -> None:
    # Extra field (`target_version`) beyond the locked six. The schema
    # is frozen with extra="forbid" so drift surfaces at ingestion,
    # not in a half-populated dashboard panel six weeks later.
    write_raw_artifact(
        "bigip-lab-01.json",
        {
            "wave": "canary",
            "device": "bigip-lab-01",
            "start": "2026-04-24T18:00:00Z",
            "end": "2026-04-24T18:05:00Z",
            "status": "success",
            "error": "",
            "target_version": "17.1.0",
        },
    )

    outcome = evaluate(artifacts_dir=artifacts_dir, threshold=1.0)

    assert outcome.passed is False
    assert "bigip-lab-01.json" in outcome.reason
    assert "schema violation" in outcome.reason


def test_schema_violation_bad_status_value_fails(
    write_raw_artifact: Callable[[str, object], Path],
    artifacts_dir: Path,
) -> None:
    write_raw_artifact(
        "bigip-lab-01.json",
        {
            "wave": "canary",
            "device": "bigip-lab-01",
            "start": "2026-04-24T18:00:00Z",
            "end": "2026-04-24T18:05:00Z",
            "status": "mostly ok",
            "error": "",
        },
    )

    outcome = evaluate(artifacts_dir=artifacts_dir, threshold=1.0)

    assert outcome.passed is False
    assert "bigip-lab-01.json" in outcome.reason


def test_schema_violation_bad_device_pattern_fails(
    write_raw_artifact: Callable[[str, object], Path],
    artifacts_dir: Path,
) -> None:
    # Device hostnames must follow bigip-{site}-NN per CLAUDE.md. An
    # artifact from a wrongly-named host indicates the workflow mis-wired
    # inventory — fail loud.
    write_raw_artifact(
        "weird-device.json",
        {
            "wave": "canary",
            "device": "not-a-bigip",
            "start": "2026-04-24T18:00:00Z",
            "end": "2026-04-24T18:05:00Z",
            "status": "success",
            "error": "",
        },
    )

    outcome = evaluate(artifacts_dir=artifacts_dir, threshold=1.0)

    assert outcome.passed is False
    assert "weird-device.json" in outcome.reason


# ---------------------------------------------------------------------------
# CLI wrapper — exit code and log tags
# ---------------------------------------------------------------------------


def test_main_exit_code_zero_on_pass(write_artifact: ArtifactFactory, artifacts_dir: Path) -> None:
    write_artifact(device="bigip-lab-01", status="success")
    buf = io.StringIO()

    exit_code = main(
        [
            "--prior-wave",
            "canary",
            "--artifacts-dir",
            str(artifacts_dir),
            "--threshold",
            "1.0",
        ],
        stdout=buf,
    )

    assert exit_code == 0
    assert "[gate-pass]" in buf.getvalue()
    assert "wave=canary" in buf.getvalue()


def test_main_exit_code_one_on_fail(write_artifact: ArtifactFactory, artifacts_dir: Path) -> None:
    write_artifact(device="bigip-lab-01", status="failed", error="install failed")
    buf = io.StringIO()

    exit_code = main(
        [
            "--prior-wave",
            "canary",
            "--artifacts-dir",
            str(artifacts_dir),
            "--threshold",
            "1.0",
        ],
        stdout=buf,
    )

    assert exit_code == 1
    assert "[gate-fail]" in buf.getvalue()
    assert "bigip-lab-01" in buf.getvalue()


def test_main_default_threshold_is_strict(
    write_artifact: ArtifactFactory, artifacts_dir: Path
) -> None:
    # No --threshold passed. Default must be 1.0 (canary's semantics).
    # If the default drifted to something looser, a single-device failure
    # would not block the gate — exactly the class of bug this test
    # exists to prevent.
    write_artifact(device="bigip-lab-01", status="success")
    write_artifact(device="bigip-lab-02", status="failed", error="boot timeout")
    buf = io.StringIO()

    exit_code = main(
        [
            "--prior-wave",
            "canary",
            "--artifacts-dir",
            str(artifacts_dir),
        ],
        stdout=buf,
    )

    assert exit_code == 1


def test_main_missing_dir_exits_one(tmp_path: Path) -> None:
    buf = io.StringIO()
    exit_code = main(
        [
            "--prior-wave",
            "canary",
            "--artifacts-dir",
            str(tmp_path / "nope"),
        ],
        stdout=buf,
    )
    assert exit_code == 1
    assert "[gate-fail]" in buf.getvalue()


def test_gate_outcome_is_frozen() -> None:
    # GateOutcome is passed around and logged; accidental mutation would
    # desync the returned reason from the displayed one.
    outcome = GateOutcome(passed=True, reason="ok")
    with pytest.raises(dataclasses.FrozenInstanceError):
        outcome.reason = "tampered"  # type: ignore[misc]
