from __future__ import annotations

from fastapi.testclient import TestClient


def test_volume_list_returns_both_volumes(client: TestClient) -> None:
    r = client.get("/mgmt/tm/sys/software/volume")
    assert r.status_code == 200
    items = r.json()["items"]
    names = {v["name"] for v in items}
    assert names == {"HD1.1", "HD1.2"}
    # Exactly one active — the BIG-IP two-volume invariant we rely on.
    active = [v for v in items if v["active"]]
    assert len(active) == 1
    assert active[0]["name"] == "HD1.1"


def test_volume_get_shows_active_flag(client: TestClient) -> None:
    r = client.get("/mgmt/tm/sys/software/volume/HD1.1")
    assert r.status_code == 200
    assert r.json()["active"] is True

    r = client.get("/mgmt/tm/sys/software/volume/HD1.2")
    assert r.status_code == 200
    assert r.json()["active"] is False


def test_volume_get_unknown_404(client: TestClient) -> None:
    r = client.get("/mgmt/tm/sys/software/volume/HD9.9")
    assert r.status_code == 404


def test_patch_active_flips_the_other_volume_to_inactive(client: TestClient) -> None:
    r = client.patch("/mgmt/tm/sys/software/volume/HD1.2", json={"active": True})
    assert r.status_code == 200
    assert r.json()["active"] is True

    # The other volume must have flipped to inactive — exactly one boots next.
    assert client.get("/mgmt/tm/sys/software/volume/HD1.1").json()["active"] is False
    assert client.get("/mgmt/tm/sys/software/volume/HD1.2").json()["active"] is True


def test_patch_active_is_idempotent(client: TestClient) -> None:
    # Activating the already-active volume is a no-op — the role must be able
    # to re-run safely.
    r1 = client.patch("/mgmt/tm/sys/software/volume/HD1.1", json={"active": True})
    r2 = client.patch("/mgmt/tm/sys/software/volume/HD1.1", json={"active": True})
    assert r1.status_code == 200
    assert r2.status_code == 200
    assert client.get("/mgmt/tm/sys/software/volume/HD1.1").json()["active"] is True
    assert client.get("/mgmt/tm/sys/software/volume/HD1.2").json()["active"] is False


def test_patch_deactivate_is_rejected(client: TestClient) -> None:
    # The two-volume invariant: a direct deactivation leaves zero active
    # volumes. The correct flip is "activate the other one".
    r = client.patch("/mgmt/tm/sys/software/volume/HD1.1", json={"active": False})
    assert r.status_code == 400


def test_patch_unknown_volume_404(client: TestClient) -> None:
    r = client.patch("/mgmt/tm/sys/software/volume/HD9.9", json={"active": True})
    assert r.status_code == 404
