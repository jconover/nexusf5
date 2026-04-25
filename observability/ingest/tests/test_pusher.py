"""Pusher tests.

The pusher is less load-bearing than the gate — a failed push is
embarrassing (empty dashboard for a run) but not dangerous (the wave
already ran, the gate already ran). Still worth pinning the behavior:

- Re-validates artifacts before pushing. A schema violation fails the
  push rather than silently dropping the offending record.
- Refuses to push an empty artifact set (same fail-closed posture as
  the gate — an empty push would zero the Grafana panels).
- Honors PUSHGATEWAY_URL env var as a fallback when --pushgateway-url
  isn't passed (workflow sources from GHA secret).
- Surfaces urllib errors as a non-zero exit; the workflow will fail
  the step rather than report a successful push that never happened.

`push_to_gateway` (from prometheus_client) is patched with a capturing
stub — it uses urllib internally so an HTTP-mock library like
`responses` wouldn't intercept it. The stub records the args it was
called with so tests can assert on what the pusher *would have* sent.
"""

from __future__ import annotations

import io
import urllib.error
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
from observability.ingest import pusher as pusher_mod
from observability.ingest.pusher import main as pusher_main


class _PushSpy:
    """Drop-in replacement for prometheus_client.push_to_gateway.

    Captures every call so tests can assert the pusher passed the
    expected gateway URL / job / grouping key / registry shape.
    """

    def __init__(self, *, raises: Exception | None = None) -> None:
        self.calls: list[dict[str, Any]] = []
        self._raises = raises

    def __call__(
        self,
        gateway: str,
        *,
        job: str,
        registry: Any,
        grouping_key: dict[str, str] | None = None,
        **_: Any,
    ) -> None:
        self.calls.append(
            {
                "gateway": gateway,
                "job": job,
                "grouping_key": grouping_key or {},
                "registry": registry,
            }
        )
        if self._raises is not None:
            raise self._raises


@pytest.fixture
def push_spy(monkeypatch: pytest.MonkeyPatch) -> _PushSpy:
    spy = _PushSpy()
    monkeypatch.setattr(pusher_mod, "push_to_gateway", spy)
    return spy


def _invoke(*args: str, stdout: io.StringIO | None = None) -> int:
    return pusher_main(list(args), stdout=stdout or io.StringIO())


def _registry_text(registry: Any) -> str:
    # prometheus_client exposes a text-format serializer; the pusher
    # hands its registry to push_to_gateway, so we can inspect what
    # would have gone over the wire without dialing a real gateway.
    from prometheus_client import generate_latest

    raw: bytes = generate_latest(registry)
    return raw.decode()


def test_pusher_happy_path_calls_push_to_gateway(
    write_artifact: Callable[..., Path], artifacts_dir: Path, push_spy: _PushSpy
) -> None:
    for i in range(1, 4):
        write_artifact(device=f"bigip-lab-{i:02d}", status="success")

    buf = io.StringIO()
    rc = _invoke(
        "--artifacts-dir",
        str(artifacts_dir),
        "--pushgateway-url",
        "http://pg.invalid",
        "--job",
        "nexusf5_wave_upgrade",
        "--wave",
        "canary",
        stdout=buf,
    )

    assert rc == 0, buf.getvalue()
    assert "[pusher-ok]" in buf.getvalue()
    assert "pushed 3 artifact(s)" in buf.getvalue()

    assert len(push_spy.calls) == 1
    call = push_spy.calls[0]
    assert call["gateway"] == "http://pg.invalid"
    assert call["job"] == "nexusf5_wave_upgrade"
    assert call["grouping_key"] == {"wave": "canary"}

    # Spot-check the registry contents — Phase 5's dashboard is built
    # against these metric names + labels.
    text = _registry_text(call["registry"])
    assert 'nexusf5_upgrade_total{status="success",wave="canary"} 3.0' in text
    assert 'nexusf5_upgrade_duration_seconds{device="bigip-lab-01",wave="canary"}' in text


def test_pusher_empty_artifacts_dir_fails(artifacts_dir: Path, push_spy: _PushSpy) -> None:
    buf = io.StringIO()
    rc = _invoke(
        "--artifacts-dir",
        str(artifacts_dir),
        "--pushgateway-url",
        "http://pg.invalid",
        "--job",
        "nexusf5_wave_upgrade",
        "--wave",
        "canary",
        stdout=buf,
    )
    assert rc == 1
    assert "no artifacts" in buf.getvalue()
    assert push_spy.calls == []  # never attempted to push


def test_pusher_schema_violation_blocks_push(
    write_raw_artifact: Callable[[str, object], Path],
    artifacts_dir: Path,
    push_spy: _PushSpy,
) -> None:
    write_raw_artifact(
        "bigip-lab-01.json",
        {"wave": "canary", "device": "bigip-lab-01", "status": "success"},
    )  # missing start/end/error
    buf = io.StringIO()
    rc = _invoke(
        "--artifacts-dir",
        str(artifacts_dir),
        "--pushgateway-url",
        "http://pg.invalid",
        "--job",
        "nexusf5_wave_upgrade",
        "--wave",
        "canary",
        stdout=buf,
    )
    assert rc == 1
    assert "schema violation" in buf.getvalue()
    assert push_spy.calls == []


def test_pusher_requires_url(
    write_artifact: Callable[..., Path],
    artifacts_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    write_artifact(device="bigip-lab-01", status="success")
    monkeypatch.delenv("PUSHGATEWAY_URL", raising=False)
    buf = io.StringIO()
    rc = _invoke(
        "--artifacts-dir",
        str(artifacts_dir),
        "--job",
        "nexusf5_wave_upgrade",
        "--wave",
        "canary",
        stdout=buf,
    )
    assert rc == 1
    assert "PUSHGATEWAY_URL not set" in buf.getvalue()


def test_pusher_reads_url_from_env(
    write_artifact: Callable[..., Path],
    artifacts_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
    push_spy: _PushSpy,
) -> None:
    write_artifact(device="bigip-lab-01", status="success")
    monkeypatch.setenv("PUSHGATEWAY_URL", "http://pg.invalid")
    buf = io.StringIO()
    rc = _invoke(
        "--artifacts-dir",
        str(artifacts_dir),
        "--job",
        "nexusf5_wave_upgrade",
        "--wave",
        "canary",
        stdout=buf,
    )
    assert rc == 0, buf.getvalue()
    assert len(push_spy.calls) == 1
    assert push_spy.calls[0]["gateway"] == "http://pg.invalid"


def test_pusher_surfaces_transport_error(
    write_artifact: Callable[..., Path],
    artifacts_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    write_artifact(device="bigip-lab-01", status="success")
    spy = _PushSpy(raises=urllib.error.URLError("pushgateway unreachable"))
    monkeypatch.setattr(pusher_mod, "push_to_gateway", spy)

    buf = io.StringIO()
    rc = _invoke(
        "--artifacts-dir",
        str(artifacts_dir),
        "--pushgateway-url",
        "http://pg.invalid",
        "--job",
        "nexusf5_wave_upgrade",
        "--wave",
        "canary",
        stdout=buf,
    )
    assert rc == 1
    assert "[pusher-fail]" in buf.getvalue()
    assert "pushgateway unreachable" in buf.getvalue()
