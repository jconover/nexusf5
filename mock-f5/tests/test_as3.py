from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

AS3_BASE = "/bigip-lab-01/mgmt/shared/appsvcs"

MIN_DECL = {
    "class": "AS3",
    "action": "deploy",
    "declaration": {
        "class": "ADC",
        "schemaVersion": "3.50.0",
        "id": "nexusf5-as3-decl-001",
        "myTenant": {
            "class": "Tenant",
            "myApp": {
                "class": "Application",
                "vip": {
                    "class": "Service_HTTP",
                    "virtualAddresses": ["10.0.0.10"],
                    "pool": "myPool",
                },
                "myPool": {
                    "class": "Pool",
                    "members": [{"servicePort": 80, "serverAddresses": ["10.0.1.10", "10.0.1.11"]}],
                },
            },
        },
    },
}


def _post(client: TestClient, tenant: str = "myTenant") -> str:
    r = client.post(f"{AS3_BASE}/declare/{tenant}?async=true", json=MIN_DECL)
    assert r.status_code == 202
    body = r.json()
    # Provider does respRef["id"].(string) with no nil check — id MUST exist.
    assert "id" in body
    assert isinstance(body["id"], str)
    assert body["results"][0]["code"] == 0
    assert body["results"][0]["tenant"] == tenant
    return str(body["id"])


def test_as3_happy_path(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MOCK_AS3_TASK_SECONDS", "0")
    task_id = _post(client)

    poll = client.get(f"{AS3_BASE}/task/{task_id}")
    assert poll.status_code == 200
    body = poll.json()
    # Status carried in results[0].code, NOT HTTP status. Provider exits on 200.
    assert body["results"][0]["code"] == 200
    assert body["results"][0]["tenant"] == "myTenant"

    read = client.get(f"{AS3_BASE}/declare/myTenant")
    assert read.status_code == 200
    # Read endpoint returns the full ADC inner block — class, schemaVersion,
    # id, and the tenant map. This matches real BIG-IP and is what the F5
    # provider's Read func writes back into `as3_json` state. Stripping the
    # ADC envelope causes drift on every subsequent terraform plan.
    assert read.json() == MIN_DECL["declaration"]


def test_as3_running_code_zero(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MOCK_AS3_TASK_SECONDS", "600")
    task_id = _post(client)
    poll = client.get(f"{AS3_BASE}/task/{task_id}")
    assert poll.status_code == 200
    assert poll.json()["results"][0]["code"] == 0


def test_as3_failure_path(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MOCK_AS3_TASK_SECONDS", "0")
    client.post("/_chaos/bigip-lab-01/fail-next-as3")
    task_id = _post(client)

    poll = client.get(f"{AS3_BASE}/task/{task_id}")
    assert poll.status_code == 200
    body = poll.json()
    assert body["results"][0]["code"] == 422
    assert "errors" in body["results"][0]

    # Read returns 404 — failed AS3 never became applied state.
    assert client.get(f"{AS3_BASE}/declare/myTenant").status_code == 404


def _post_for(client: TestClient, tenant: str) -> str:
    decl = {
        "class": "AS3",
        "action": "deploy",
        "declaration": {
            "class": "ADC",
            "schemaVersion": "3.50.0",
            "id": f"id-{tenant}",
            tenant: {
                "class": "Tenant",
                "myApp": {"class": "Application", "template": "http"},
            },
        },
    }
    r = client.post(f"{AS3_BASE}/declare/{tenant}?async=true", json=decl)
    assert r.status_code == 202
    return str(r.json()["id"])


def test_as3_multi_tenant_isolation(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MOCK_AS3_TASK_SECONDS", "0")

    a = _post_for(client, "tenantA")
    client.get(f"{AS3_BASE}/task/{a}")

    b = _post_for(client, "tenantB")
    client.get(f"{AS3_BASE}/task/{b}")

    assert client.get(f"{AS3_BASE}/declare/tenantA").status_code == 200
    assert client.get(f"{AS3_BASE}/declare/tenantB").status_code == 200
    # Unknown tenant doesn't leak from the others.
    assert client.get(f"{AS3_BASE}/declare/tenantC").status_code == 404


def test_as3_drift_postcheck_mutates_read(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("MOCK_AS3_TASK_SECONDS", "0")
    task_id = _post(client)
    client.get(f"{AS3_BASE}/task/{task_id}")

    assert "__drift_marker" not in client.get(f"{AS3_BASE}/declare/myTenant").json()
    client.post("/_chaos/bigip-lab-01/drift-postcheck")
    body = client.get(f"{AS3_BASE}/declare/myTenant").json()
    assert body["__drift_marker"] == "chaos.drift_postcheck"
    # Tenant block still surfaces; drift only adds the marker.
    assert "myTenant" in body


def test_as3_unknown_task_404(client: TestClient) -> None:
    r = client.get(f"{AS3_BASE}/task/00000000-0000-0000-0000-000000000000")
    assert r.status_code == 404


def test_as3_failure_chaos_is_one_shot(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MOCK_AS3_TASK_SECONDS", "0")
    client.post("/_chaos/bigip-lab-01/fail-next-as3")
    fail_id = _post(client)
    client.get(f"{AS3_BASE}/task/{fail_id}")

    ok_id = _post(client)
    poll = client.get(f"{AS3_BASE}/task/{ok_id}")
    assert poll.json()["results"][0]["code"] == 200


def test_as3_double_encoded_body(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    """F5 provider v1.26 sends as3_json/do_json as a JSON-encoded *string*,
    not a JSON object. The mock has to treat both wire shapes as equivalent
    so terraform apply against the lab env actually round-trips."""
    import json as _json

    monkeypatch.setenv("MOCK_AS3_TASK_SECONDS", "0")
    body = _json.dumps(MIN_DECL)  # JSON-encoded string -> wire body is "..."
    r = client.post(
        f"{AS3_BASE}/declare/myTenant?async=true",
        content=_json.dumps(body),
        headers={"Content-Type": "application/json"},
    )
    assert r.status_code == 202
    task_id = r.json()["id"]
    client.get(f"{AS3_BASE}/task/{task_id}")

    read = client.get(f"{AS3_BASE}/declare/myTenant")
    assert read.status_code == 200
    # Read returns the parsed dict shape, not a JSON-encoded string.
    assert read.json() == MIN_DECL["declaration"]
