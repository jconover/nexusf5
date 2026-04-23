from __future__ import annotations

import time

import pytest
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


def test_install_post_returns_in_progress_by_default(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    # 30s default makes the install visibly pending right after POST.
    monkeypatch.setenv("MOCK_INSTALL_SECONDS", "30")
    r = client.post(
        "/mgmt/tm/sys/software/volume",
        json={"command": "install", "name": "HD1.2", "version": "17.1.0"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "in progress"
    assert body["name"] == "HD1.2"

    # Polling the specific volume shows the same in-progress status until it
    # completes — this is what the f5_image_install role loops on.
    r = client.get("/mgmt/tm/sys/software/volume/HD1.2")
    assert r.json()["status"] == "in progress"


def test_install_completes_instantly_with_zero_timing(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("MOCK_INSTALL_SECONDS", "0")
    client.post(
        "/mgmt/tm/sys/software/volume",
        json={"command": "install", "name": "HD1.2", "version": "17.1.0"},
    )
    # Any subsequent request triggers advance() and sees the op complete.
    r = client.get("/mgmt/tm/sys/software/volume/HD1.2")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "complete"
    assert body["version"] == "17.1.0"


def test_install_timeout_still_in_progress_after_short_wait(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Install takes 10 minutes — a realistic-ish timeout scenario. Polling
    # after a short wait must still report in-progress so the ansible role's
    # timeout branch would fire.
    monkeypatch.setenv("MOCK_INSTALL_SECONDS", "600")
    client.post(
        "/mgmt/tm/sys/software/volume",
        json={"command": "install", "name": "HD1.2", "version": "17.1.0"},
    )
    time.sleep(0.05)
    r = client.get("/mgmt/tm/sys/software/volume/HD1.2")
    assert r.json()["status"] == "in progress"


def test_install_requires_name_and_version(client: TestClient) -> None:
    r = client.post("/mgmt/tm/sys/software/volume", json={"command": "install"})
    assert r.status_code == 400


def test_install_unknown_volume_404(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MOCK_INSTALL_SECONDS", "0")
    r = client.post(
        "/mgmt/tm/sys/software/volume",
        json={"command": "install", "name": "HD9.9", "version": "17.1.0"},
    )
    assert r.status_code == 404
