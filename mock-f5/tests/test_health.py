from __future__ import annotations

from fastapi.testclient import TestClient


def test_health_reports_registered_device(client: TestClient) -> None:
    r = client.get("/health")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert "bigip-lab-01" in body["devices"]


def test_metrics_exposes_device_labels(client: TestClient) -> None:
    r = client.get("/metrics")
    assert r.status_code == 200
    text = r.text
    assert "nexusf5_mock_device_info" in text
    assert 'hostname="bigip-lab-01"' in text
    assert "nexusf5_mock_connections" in text
