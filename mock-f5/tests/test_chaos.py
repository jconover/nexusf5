from __future__ import annotations

from fastapi.testclient import TestClient


def test_fail_next_install_triggers_500(client: TestClient) -> None:
    r = client.post("/_chaos/bigip-lab-01/fail-next-install")
    assert r.status_code == 200
    r = client.post(
        "/mgmt/tm/sys/software/volume",
        json={"command": "install", "name": "HD1.2", "version": "17.1.0"},
    )
    assert r.status_code == 500


def test_fail_next_install_is_one_shot(client: TestClient) -> None:
    client.post("/_chaos/bigip-lab-01/fail-next-install")
    client.post(
        "/mgmt/tm/sys/software/volume",
        json={"command": "install", "name": "HD1.2", "version": "17.1.0"},
    )
    # Second install should succeed — the chaos flag consumes itself.
    r = client.post(
        "/mgmt/tm/sys/software/volume",
        json={"command": "install", "name": "HD1.2", "version": "17.1.0"},
    )
    assert r.status_code == 200


def test_chaos_reset_clears_all_flags(client: TestClient) -> None:
    client.post("/_chaos/bigip-lab-01/fail-next-install")
    r = client.post("/_chaos/bigip-lab-01/reset")
    assert r.status_code == 200
    r = client.post(
        "/mgmt/tm/sys/software/volume",
        json={"command": "install", "name": "HD1.2", "version": "17.1.0"},
    )
    assert r.status_code == 200


def test_chaos_unknown_host_404(client: TestClient) -> None:
    r = client.post("/_chaos/bigip-lab-99/fail-next-install")
    assert r.status_code == 404


def test_chaos_slow_reboot_toggle(client: TestClient) -> None:
    r = client.post("/_chaos/bigip-lab-01/slow-reboot")
    assert r.status_code == 200
    assert r.json()["flag"] == "slow_reboot"


def test_chaos_post_boot_unhealthy_toggle(client: TestClient) -> None:
    r = client.post("/_chaos/bigip-lab-01/post-boot-unhealthy")
    assert r.status_code == 200
    assert r.json()["flag"] == "post_boot_unhealthy"


def test_chaos_drift_postcheck_toggle(client: TestClient) -> None:
    r = client.post("/_chaos/bigip-lab-01/drift-postcheck")
    assert r.status_code == 200
    assert r.json()["flag"] == "drift_postcheck"
