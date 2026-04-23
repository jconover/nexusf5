from __future__ import annotations

from fastapi.testclient import TestClient


def test_software_image_register(client: TestClient) -> None:
    r = client.post(
        "/mgmt/tm/sys/software/image",
        json={"command": "install", "name": "BIGIP-17.1.0-0.0.3.iso"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["name"] == "BIGIP-17.1.0-0.0.3.iso"
    assert body["kind"] == "tm:sys:software:image:imagestate"


def test_software_volume_install_updates_version(client: TestClient) -> None:
    r = client.post(
        "/mgmt/tm/sys/software/volume",
        json={"command": "install", "name": "HD1.2", "version": "17.1.0"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "complete"
    assert body["version"] == "17.1.0"
