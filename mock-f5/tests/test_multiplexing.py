"""Multi-device routing tests for the Phase 3 multiplexed mock.

The in-process `client` fixture boots a single-device store (good enough
for endpoint-shape tests); here we spin up a dedicated app with a small
multi-device manifest so we can prove:

- Each device resolves via its own hostname path prefix.
- State is independent: a reboot on device A does not affect device B.
- Unknown hostnames return 404 with a useful message.
- `/health` and `/metrics` live at the root and enumerate all devices.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.main import app


@pytest.fixture
def multiplex_client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    manifest = tmp_path / "devices.json"
    manifest.write_text(
        json.dumps(
            {
                "devices": [
                    {"hostname": "bigip-lab-01", "version": "16.1.3"},
                    {"hostname": "bigip-lab-02", "version": "16.1.3"},
                    {"hostname": "bigip-lab-03", "version": "16.1.3"},
                ]
            }
        )
    )
    monkeypatch.setenv("MOCK_F5_MANIFEST", str(manifest))
    monkeypatch.setenv("MOCK_REBOOT_SECONDS", "0")
    monkeypatch.setenv("MOCK_INSTALL_SECONDS", "0")
    with TestClient(app) as c:
        yield c


def _version(client: TestClient, host: str) -> str:
    r = client.get(f"/{host}/mgmt/tm/sys/version")
    assert r.status_code == 200, r.text
    entry = next(iter(r.json()["entries"].values()))
    return entry["nestedStats"]["entries"]["Version"]["description"]


def test_each_device_resolves_via_its_own_path_prefix(
    multiplex_client: TestClient,
) -> None:
    for host in ("bigip-lab-01", "bigip-lab-02", "bigip-lab-03"):
        assert _version(multiplex_client, host) == "16.1.3"


def test_unknown_host_returns_404(multiplex_client: TestClient) -> None:
    r = multiplex_client.get("/bigip-lab-99/mgmt/tm/sys/version")
    assert r.status_code == 404
    assert "bigip-lab-99" in r.json()["detail"]


def test_reboot_on_one_device_does_not_affect_peers(
    multiplex_client: TestClient,
) -> None:
    # Install a new image to HD1.2 on host 01 and boot into it.
    install = multiplex_client.post(
        "/bigip-lab-01/mgmt/tm/sys/software/volume",
        json={"command": "install", "name": "HD1.2", "version": "17.1.0"},
    )
    assert install.status_code == 200, install.text
    multiplex_client.patch(
        "/bigip-lab-01/mgmt/tm/sys/software/volume/HD1.2",
        json={"active": True},
    )
    multiplex_client.post(
        "/bigip-lab-01/mgmt/tm/util/bash",
        json={"command": "run", "utilCmdArgs": "-c 'reboot'"},
    )

    # With MOCK_REBOOT_SECONDS=0 the reboot completes on the next handler
    # call. Verify host 01 reflects the new version and host 02 is untouched.
    assert _version(multiplex_client, "bigip-lab-01") == "17.1.0"
    assert _version(multiplex_client, "bigip-lab-02") == "16.1.3"


def test_chaos_is_scoped_to_named_device(multiplex_client: TestClient) -> None:
    r = multiplex_client.post("/_chaos/bigip-lab-02/fail-next-install")
    assert r.status_code == 200

    # Install to host 03 should succeed (chaos is on host 02 only).
    multiplex_client.post(
        "/bigip-lab-03/mgmt/tm/sys/software/volume",
        json={"command": "install", "name": "HD1.2", "version": "17.1.0"},
    )
    status_03 = multiplex_client.get("/bigip-lab-03/mgmt/tm/sys/software/volume/HD1.2")
    assert status_03.json()["version"] == "17.1.0"

    # Install to host 02 should fail (chaos consumed on the attempt).
    multiplex_client.post(
        "/bigip-lab-02/mgmt/tm/sys/software/volume",
        json={"command": "install", "name": "HD1.2", "version": "17.1.0"},
    )
    status_02 = multiplex_client.get("/bigip-lab-02/mgmt/tm/sys/software/volume/HD1.2")
    assert status_02.json()["status"] == "failed"


def test_health_and_metrics_enumerate_all_devices(
    multiplex_client: TestClient,
) -> None:
    health = multiplex_client.get("/health").json()
    assert set(health["devices"]) == {
        "bigip-lab-01",
        "bigip-lab-02",
        "bigip-lab-03",
    }

    metrics = multiplex_client.get("/metrics").text
    for host in ("bigip-lab-01", "bigip-lab-02", "bigip-lab-03"):
        assert f'hostname="{host}"' in metrics


def test_manifest_with_duplicate_hostnames_fails_fast(tmp_path: Path) -> None:
    # Guardrail: duplicate hostnames must fail at startup, not silently
    # collapse to a single device that drops traffic intended for the other.
    from app.state import build_store_from_manifest

    manifest = tmp_path / "dupes.json"
    manifest.write_text(
        json.dumps(
            {
                "devices": [
                    {"hostname": "bigip-lab-01"},
                    {"hostname": "bigip-lab-01"},
                ]
            }
        )
    )
    with pytest.raises(ValueError, match="duplicate hostname"):
        build_store_from_manifest(manifest)
