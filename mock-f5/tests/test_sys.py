from __future__ import annotations

from fastapi.testclient import TestClient


def test_performance_all_stats_shape(client: TestClient) -> None:
    r = client.get("/mgmt/tm/sys/performance/all-stats")
    assert r.status_code == 200
    body = r.json()
    assert body["kind"].startswith("tm:sys:performance")
    keys = list(body["entries"].keys())
    assert any("CPU%20Usage" in k for k in keys)
    assert any("Memory%20Used" in k for k in keys)
    assert any("Active%20Connections" in k for k in keys)


def test_ucs_save_echoes_name(client: TestClient) -> None:
    r = client.post("/mgmt/tm/sys/ucs", json={"command": "save", "name": "backup.ucs"})
    assert r.status_code == 200
    assert r.json()["name"] == "backup.ucs"


def test_ucs_save_defaults_name_when_absent(client: TestClient) -> None:
    r = client.post("/mgmt/tm/sys/ucs", json={"command": "save"})
    assert r.status_code == 200
    assert r.json()["name"].endswith(".ucs")


def test_failover_toggles_state(client: TestClient) -> None:
    before = (
        client.get("/mgmt/tm/cm/failover-status")
        .json()["entries"]
        .popitem()[1]["nestedStats"]["entries"]["status"]["description"]
    )
    r = client.post("/mgmt/tm/sys/failover", json={"command": "run"})
    assert r.status_code == 200
    after = (
        client.get("/mgmt/tm/cm/failover-status")
        .json()["entries"]
        .popitem()[1]["nestedStats"]["entries"]["status"]["description"]
    )
    assert before != after
