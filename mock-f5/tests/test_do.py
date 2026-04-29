from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

DO_BASE = "/bigip-lab-01/mgmt/shared/declarative-onboarding"

MIN_DECL = {
    "schemaVersion": "1.40.0",
    "class": "DO",
    "declaration": {
        "schemaVersion": "1.40.0",
        "class": "Device",
        "Common": {
            "class": "Tenant",
            "myHostname": {
                "class": "System",
                "hostname": "bigip-lab-01.local",
            },
        },
    },
}


def _post_decl(client: TestClient) -> str:
    r = client.post(DO_BASE, json=MIN_DECL)
    assert r.status_code == 202
    body = r.json()
    assert body["result"]["status"] == "RUNNING"
    assert "id" in body
    return str(body["id"])


def test_do_happy_path(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MOCK_DO_TASK_SECONDS", "0")
    task_id = _post_decl(client)

    poll = client.get(f"{DO_BASE}/task/{task_id}")
    assert poll.status_code == 200
    body = poll.json()
    assert body["result"]["status"] == "OK"
    assert body["declaration"] == MIN_DECL

    read = client.get(DO_BASE)
    assert read.status_code == 200
    assert read.json() == MIN_DECL


def test_do_running_returns_202(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    # Long task — first poll must report RUNNING with HTTP 202.
    monkeypatch.setenv("MOCK_DO_TASK_SECONDS", "600")
    task_id = _post_decl(client)
    poll = client.get(f"{DO_BASE}/task/{task_id}")
    assert poll.status_code == 202
    assert poll.json()["result"]["status"] == "RUNNING"


def test_do_failure_path(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MOCK_DO_TASK_SECONDS", "0")
    client.post("/_chaos/bigip-lab-01/fail-next-do")
    task_id = _post_decl(client)

    poll = client.get(f"{DO_BASE}/task/{task_id}")
    # ERROR is carried on a 202 per provider contract.
    assert poll.status_code == 202
    body = poll.json()
    assert body["result"]["status"] == "ERROR"
    assert "fail_next_do" in body["result"]["message"] or "failed" in body["result"]["message"]

    # Failed task does NOT become the read-endpoint declaration.
    read = client.get(DO_BASE)
    assert read.status_code == 204


def test_do_failure_chaos_is_one_shot(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MOCK_DO_TASK_SECONDS", "0")
    client.post("/_chaos/bigip-lab-01/fail-next-do")
    fail_id = _post_decl(client)
    client.get(f"{DO_BASE}/task/{fail_id}")

    # Second post should succeed because chaos consumed itself.
    ok_id = _post_decl(client)
    poll = client.get(f"{DO_BASE}/task/{ok_id}")
    assert poll.status_code == 200
    assert poll.json()["result"]["status"] == "OK"


def test_do_drift_postcheck_mutates_read(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("MOCK_DO_TASK_SECONDS", "0")
    task_id = _post_decl(client)
    client.get(f"{DO_BASE}/task/{task_id}")

    # Pre-chaos read returns clean.
    assert "__drift_marker" not in client.get(DO_BASE).json()

    client.post("/_chaos/bigip-lab-01/drift-postcheck")
    body = client.get(DO_BASE).json()
    assert body["__drift_marker"] == "chaos.drift_postcheck"

    # Clearing chaos returns the read to clean (one-shot via reset).
    client.post("/_chaos/bigip-lab-01/reset")
    assert "__drift_marker" not in client.get(DO_BASE).json()


def test_do_unknown_task_404(client: TestClient) -> None:
    r = client.get(f"{DO_BASE}/task/00000000-0000-0000-0000-000000000000")
    assert r.status_code == 404


def test_do_read_no_state_returns_204(client: TestClient) -> None:
    assert client.get(DO_BASE).status_code == 204


def test_do_double_encoded_body(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    """F5 provider v1.26 sends do_json as a JSON-encoded *string*, not a
    JSON object. Mock must treat both shapes as equivalent."""
    import json as _json

    monkeypatch.setenv("MOCK_DO_TASK_SECONDS", "0")
    r = client.post(
        DO_BASE,
        content=_json.dumps(_json.dumps(MIN_DECL)),
        headers={"Content-Type": "application/json"},
    )
    assert r.status_code == 202
    task_id = r.json()["id"]
    poll = client.get(f"{DO_BASE}/task/{task_id}")
    assert poll.status_code == 200
    assert poll.json()["declaration"] == MIN_DECL

    read = client.get(DO_BASE)
    assert read.status_code == 200
    assert read.json() == MIN_DECL
