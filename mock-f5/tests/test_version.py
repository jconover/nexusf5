from __future__ import annotations

from fastapi.testclient import TestClient


def test_sys_version_shape(client: TestClient) -> None:
    r = client.get("/mgmt/tm/sys/version")
    assert r.status_code == 200
    body = r.json()
    assert body["kind"] == "tm:sys:version:versionstats"
    entry = next(iter(body["entries"].values()))
    fields = entry["nestedStats"]["entries"]
    assert fields["Version"]["description"] == "16.1.3"
    assert fields["Product"]["description"] == "BIG-IP"
    assert "Build" in fields
    assert "Edition" in fields
