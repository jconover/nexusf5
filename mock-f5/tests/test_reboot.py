from __future__ import annotations

import time

import pytest
from fastapi.testclient import TestClient


def test_util_bash_non_reboot_is_noop(client: TestClient) -> None:
    r = client.post(
        "/mgmt/tm/util/bash",
        json={"command": "run", "utilCmdArgs": "-c 'ls /etc'"},
    )
    assert r.status_code == 200
    # Did not trigger reboot — version endpoint still responds 200.
    assert client.get("/mgmt/tm/sys/version").status_code == 200


def test_util_bash_reboot_starts_window_and_blocks_icontrol(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Reboot takes 5 min — plenty of headroom for the test to observe the
    # rebooting window with a single request.
    monkeypatch.setenv("MOCK_REBOOT_SECONDS", "300")
    r = client.post(
        "/mgmt/tm/util/bash",
        json={"command": "run", "utilCmdArgs": "-c 'tmsh reboot'"},
    )
    assert r.status_code == 200

    # Any iControl REST request during the reboot window is 503.
    r = client.get("/mgmt/tm/sys/version")
    assert r.status_code == 503
    assert r.headers.get("Retry-After") == "5"


def test_reboot_completes_instantly_and_updates_version(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("MOCK_INSTALL_SECONDS", "0")
    monkeypatch.setenv("MOCK_REBOOT_SECONDS", "0")

    # Install 17.1.0 to the inactive volume.
    client.post(
        "/mgmt/tm/sys/software/volume",
        json={"command": "install", "name": "HD1.2", "version": "17.1.0"},
    )
    # Activate HD1.2 as next boot.
    client.patch("/mgmt/tm/sys/software/volume/HD1.2", json={"active": True})
    # Reboot.
    client.post(
        "/mgmt/tm/util/bash",
        json={"command": "run", "utilCmdArgs": "-c 'tmsh reboot'"},
    )

    # Zero-timing reboot has already completed at the next request.
    r = client.get("/mgmt/tm/sys/version")
    assert r.status_code == 200
    fields = next(iter(r.json()["entries"].values()))["nestedStats"]["entries"]
    assert fields["Version"]["description"] == "17.1.0"


def test_reboot_does_not_advance_version_if_active_volume_not_changed(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Rebooting without flipping active keeps the same version — this is the
    # rollback-safety invariant: "reboot alone" is not a version change.
    monkeypatch.setenv("MOCK_REBOOT_SECONDS", "0")
    client.post(
        "/mgmt/tm/util/bash",
        json={"command": "run", "utilCmdArgs": "-c 'tmsh reboot'"},
    )
    # A small pause lets reboot_seconds=0 expire past the handler's now().
    time.sleep(0.01)
    r = client.get("/mgmt/tm/sys/version")
    fields = next(iter(r.json()["entries"].values()))["nestedStats"]["entries"]
    assert fields["Version"]["description"] == "16.1.3"
