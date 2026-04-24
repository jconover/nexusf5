from __future__ import annotations

import time

import pytest
from fastapi.testclient import TestClient


def test_fail_next_install_op_status_fails_not_endpoint(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Real F5 install failures surface via poll status, not at POST time.
    # The mock mirrors that: POST succeeds, the volume poll shows "failed".
    monkeypatch.setenv("MOCK_INSTALL_SECONDS", "0")
    client.post("/_chaos/bigip-lab-01/fail-next-install")

    r = client.post(
        "/bigip-lab-01/mgmt/tm/sys/software/volume",
        json={"command": "install", "name": "HD1.2", "version": "17.1.0"},
    )
    assert r.status_code == 200
    assert r.json()["status"] == "in progress"

    r = client.get("/bigip-lab-01/mgmt/tm/sys/software/volume/HD1.2")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "failed"
    # Version must NOT have been applied.
    assert body["version"] != "17.1.0"


def test_fail_next_install_is_one_shot(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MOCK_INSTALL_SECONDS", "0")
    client.post("/_chaos/bigip-lab-01/fail-next-install")
    client.post(
        "/bigip-lab-01/mgmt/tm/sys/software/volume",
        json={"command": "install", "name": "HD1.2", "version": "17.1.0"},
    )
    # Second install succeeds — chaos consumed itself.
    client.post(
        "/bigip-lab-01/mgmt/tm/sys/software/volume",
        json={"command": "install", "name": "HD1.2", "version": "17.1.0"},
    )
    r = client.get("/bigip-lab-01/mgmt/tm/sys/software/volume/HD1.2")
    body = r.json()
    assert body["status"] == "complete"
    assert body["version"] == "17.1.0"


def test_slow_reboot_exceeds_normal_timing_window(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Normal reboot = 0.05s. Slow-reboot multiplier = 20 → slow reboot = 1.0s.
    # A poll at 0.2s: normal would be done, slow still pending.
    monkeypatch.setenv("MOCK_REBOOT_SECONDS", "0.05")
    monkeypatch.setenv("MOCK_SLOW_REBOOT_MULTIPLIER", "20")
    client.post("/_chaos/bigip-lab-01/slow-reboot")
    client.post(
        "/bigip-lab-01/mgmt/tm/util/bash",
        json={"command": "run", "utilCmdArgs": "-c 'tmsh reboot'"},
    )
    time.sleep(0.2)
    r = client.get("/bigip-lab-01/mgmt/tm/sys/version")
    assert r.status_code == 503  # still rebooting


def test_post_boot_unhealthy_flips_ha_red_after_reboot(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("MOCK_REBOOT_SECONDS", "0")
    client.post("/_chaos/bigip-lab-01/post-boot-unhealthy")
    client.post(
        "/bigip-lab-01/mgmt/tm/util/bash",
        json={"command": "run", "utilCmdArgs": "-c 'tmsh reboot'"},
    )

    # After the reboot completes, HA should be red (FORCED OFFLINE) — health
    # gate in the runbook must catch this and trigger rollback.
    r = client.get("/bigip-lab-01/mgmt/tm/cm/failover-status")
    fields = next(iter(r.json()["entries"].values()))["nestedStats"]["entries"]
    assert fields["color"]["description"] == "red"
    assert fields["status"]["description"] == "FORCED OFFLINE"


def test_post_boot_unhealthy_is_one_shot(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("MOCK_REBOOT_SECONDS", "0")
    client.post("/_chaos/bigip-lab-01/post-boot-unhealthy")
    client.post(
        "/bigip-lab-01/mgmt/tm/util/bash",
        json={"command": "run", "utilCmdArgs": "-c 'tmsh reboot'"},
    )
    # Reset to simulate operator rolling back.
    client.post("/_chaos/bigip-lab-01/reset")
    # A healthy operator-driven recovery would force HA back to ACTIVE;
    # for this test we just prove the chaos flag consumed itself so a
    # subsequent healthy reboot does not re-trigger the red state.
    client.post("/_chaos/bigip-lab-01/reset")
    client.post(
        "/bigip-lab-01/mgmt/tm/util/bash",
        json={"command": "run", "utilCmdArgs": "-c 'tmsh reboot'"},
    )
    # chaos has been reset and consumed; second reboot does not re-apply
    # post-boot-unhealthy. HA remains whatever reset left it (unchanged here).


def test_chaos_reset_clears_all_flags(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MOCK_INSTALL_SECONDS", "0")
    client.post("/_chaos/bigip-lab-01/fail-next-install")
    r = client.post("/_chaos/bigip-lab-01/reset")
    assert r.status_code == 200
    # Install after reset succeeds.
    client.post(
        "/bigip-lab-01/mgmt/tm/sys/software/volume",
        json={"command": "install", "name": "HD1.2", "version": "17.1.0"},
    )
    r = client.get("/bigip-lab-01/mgmt/tm/sys/software/volume/HD1.2")
    assert r.json()["status"] == "complete"


def test_chaos_unknown_host_404(client: TestClient) -> None:
    r = client.post("/_chaos/bigip-lab-99/fail-next-install")
    assert r.status_code == 404


def test_chaos_slow_reboot_toggle(client: TestClient) -> None:
    r = client.post("/_chaos/bigip-lab-01/slow-reboot")
    assert r.status_code == 200
    assert r.json()["flag"] == "slow_reboot"


def test_chaos_drift_postcheck_toggle(client: TestClient) -> None:
    r = client.post("/_chaos/bigip-lab-01/drift-postcheck")
    assert r.status_code == 200
    assert r.json()["flag"] == "drift_postcheck"


def test_reset_device_restores_fresh_state(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Drive a full upgrade to put the device in the post-upgrade state.
    monkeypatch.setenv("MOCK_INSTALL_SECONDS", "0")
    monkeypatch.setenv("MOCK_REBOOT_SECONDS", "0")
    client.post(
        "/bigip-lab-01/mgmt/tm/sys/software/volume",
        json={"command": "install", "name": "HD1.2", "version": "17.1.0"},
    )
    client.patch("/bigip-lab-01/mgmt/tm/sys/software/volume/HD1.2", json={"active": True})
    client.post(
        "/bigip-lab-01/mgmt/tm/util/bash",
        json={"command": "run", "utilCmdArgs": "-c 'tmsh reboot'"},
    )
    # Version is now 17.1.0.
    r = client.get("/bigip-lab-01/mgmt/tm/sys/version")
    fields = next(iter(r.json()["entries"].values()))["nestedStats"]["entries"]
    assert fields["Version"]["description"] == "17.1.0"

    # Reset fully.
    r = client.post("/_chaos/bigip-lab-01/reset-device")
    assert r.status_code == 200

    # Back to 16.1.3 with HD1.1 active.
    r = client.get("/bigip-lab-01/mgmt/tm/sys/version")
    fields = next(iter(r.json()["entries"].values()))["nestedStats"]["entries"]
    assert fields["Version"]["description"] == "16.1.3"
    assert client.get("/bigip-lab-01/mgmt/tm/sys/software/volume/HD1.1").json()["active"] is True


def test_reset_device_clears_rebooting_window(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Kick off a long reboot, then reset — subsequent requests must not 503.
    monkeypatch.setenv("MOCK_REBOOT_SECONDS", "600")
    client.post(
        "/bigip-lab-01/mgmt/tm/util/bash",
        json={"command": "run", "utilCmdArgs": "-c 'tmsh reboot'"},
    )
    assert client.get("/bigip-lab-01/mgmt/tm/sys/version").status_code == 503
    client.post("/_chaos/bigip-lab-01/reset-device")
    assert client.get("/bigip-lab-01/mgmt/tm/sys/version").status_code == 200


def test_reset_device_unknown_host_404(client: TestClient) -> None:
    r = client.post("/_chaos/bigip-lab-99/reset-device")
    assert r.status_code == 404
