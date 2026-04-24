from __future__ import annotations

from fastapi.testclient import TestClient


def test_failover_status_default_active_green(client: TestClient) -> None:
    r = client.get("/bigip-lab-01/mgmt/tm/cm/failover-status")
    assert r.status_code == 200
    fields = next(iter(r.json()["entries"].values()))["nestedStats"]["entries"]
    assert fields["status"]["description"] == "ACTIVE"
    assert fields["color"]["description"] == "green"


def test_sync_status_default_in_sync_green(client: TestClient) -> None:
    r = client.get("/bigip-lab-01/mgmt/tm/cm/sync-status")
    assert r.status_code == 200
    fields = next(iter(r.json()["entries"].values()))["nestedStats"]["entries"]
    assert fields["status"]["description"] == "In Sync"
    assert fields["color"]["description"] == "green"
