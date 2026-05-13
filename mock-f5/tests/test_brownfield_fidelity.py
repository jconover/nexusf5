"""Tests for the LTM + DO /inspect endpoints the brownfield-extractor walks.

Per ADR 007, these endpoints are the mock-side contract the extractor reads
against. The tests assert:

  1. Each endpoint returns a 200 with the documented F5 envelope shape
     (`kind`, `selfLink`, `items`) for collections and the documented
     array-of-task shape for `/inspect`.
  2. Hostname templating works (selfLink fields carry the device hostname
     from the URL path, not a hard-coded value).
  3. Cross-references resolve within the fixture set — virtual.pool points
     at pool.fullPath, pool.monitor points at monitor_http.fullPath, etc.
     A dangling reference here is an extractor-time crash later.
  4. The `/inspect` Device declaration passes the ADR 006 vendored-schema
     validator. This is the load-bearing gate per ADR 007 §Testing
     strategy: a declaration the mock returns that fails the schema
     validator is a fixture bug, by construction.

The `client` fixture from conftest registers `bigip-lab-01` at startup.
"""

from __future__ import annotations

from typing import Any

from fastapi.testclient import TestClient

from app.schemas import validate_do_declaration

LTM_BASE = "/bigip-lab-01/mgmt/tm/ltm"
INSPECT_PATH = "/bigip-lab-01/mgmt/shared/declarative-onboarding/inspect"


def _items(client: TestClient, path: str) -> list[dict[str, Any]]:
    r = client.get(path)
    assert r.status_code == 200, f"{path} returned {r.status_code}: {r.text[:200]}"
    body = r.json()
    assert "kind" in body, f"{path} body missing 'kind': {body}"
    assert "selfLink" in body, f"{path} body missing 'selfLink': {body}"
    assert "items" in body, f"{path} body missing 'items': {body}"
    assert "bigip-lab-01" in body["selfLink"], (
        f"{path} selfLink not hostname-templated: {body['selfLink']}"
    )
    items: list[dict[str, Any]] = body["items"]
    assert items, f"{path} returned empty items collection"
    return items


def test_ltm_virtual_shape(client: TestClient) -> None:
    items = _items(client, f"{LTM_BASE}/virtual")
    names = {v["name"] for v in items}
    assert names == {"example_http_vs", "example_https_vs"}
    https_vs = next(v for v in items if v["name"] == "example_https_vs")
    # ClientSSL on the HTTPS virtual carries clientside context per F5 contract.
    profiles = https_vs["profiles"]
    assert "/Common/example_clientssl" in profiles
    assert profiles["/Common/example_clientssl"]["context"] == "clientside"


def test_ltm_pool_shape(client: TestClient) -> None:
    items = _items(client, f"{LTM_BASE}/pool")
    pool = items[0]
    assert pool["fullPath"] == "/Common/example_pool"
    assert pool["membersReference"]["isSubcollection"] is True
    assert "bigip-lab-01" in pool["membersReference"]["link"]


def test_ltm_pool_members_shape(client: TestClient) -> None:
    items = _items(client, f"{LTM_BASE}/pool/example_pool/members")
    assert len(items) == 3
    enabled = [m for m in items if m["session"] == "user-enabled"]
    disabled = [m for m in items if m["session"] == "user-disabled"]
    assert len(enabled) == 2, f"expected 2 user-enabled members, got {len(enabled)}"
    assert len(disabled) == 1, f"expected 1 user-disabled member, got {len(disabled)}"


def test_ltm_monitor_http_shape(client: TestClient) -> None:
    items = _items(client, f"{LTM_BASE}/monitor/http")
    mon = items[0]
    assert mon["fullPath"] == "/Common/example_http_monitor"
    # Custom send must contain a non-default URI to be representative —
    # ADR 007's §Scope of the first cut requires a "custom HTTP monitor
    # with non-default send/recv strings."
    assert "/health" in mon["send"], "send field expected non-default URI"
    assert mon["defaultsFrom"] == "/Common/http"


def test_ltm_profile_clientssl_shape(client: TestClient) -> None:
    items = _items(client, f"{LTM_BASE}/profile/client-ssl")
    prof = items[0]
    assert prof["fullPath"] == "/Common/example_clientssl"
    cert_chain = prof["certKeyChain"]
    assert len(cert_chain) == 1
    entry = cert_chain[0]
    assert entry["cert"].endswith(".crt"), f"cert path not .crt: {entry['cert']}"
    assert entry["key"].endswith(".key"), f"key path not .key: {entry['key']}"


def test_ltm_persistence_cookie_shape(client: TestClient) -> None:
    items = _items(client, f"{LTM_BASE}/persistence/cookie")
    persist = items[0]
    assert persist["fullPath"] == "/Common/cookie_persist"
    assert persist["method"] == "insert"
    assert persist["cookieName"] == "SERVERID"


def test_ltm_rule_shape(client: TestClient) -> None:
    items = _items(client, f"{LTM_BASE}/rule")
    rule = items[0]
    assert rule["fullPath"] == "/Common/example_irule"
    # Verbatim TCL body must be multi-line and contain expected commands —
    # the extractor will pass this through as AS3 `iRule` content as-is.
    body = rule["apiAnonymous"]
    assert "when HTTP_REQUEST" in body
    assert "\n" in body, "iRule body should retain newlines"


def test_ltm_cross_references_resolve(client: TestClient) -> None:
    """The extractor walks LTM and follows references between objects.
    A dangling reference (virtual.pool → nonexistent pool) is a runtime crash.
    Verify the fixture set is self-consistent so the extractor's first PR
    doesn't have to ship workarounds for fixture bugs.
    """
    virtuals = _items(client, f"{LTM_BASE}/virtual")
    pools = _items(client, f"{LTM_BASE}/pool")
    monitors = _items(client, f"{LTM_BASE}/monitor/http")
    profiles = _items(client, f"{LTM_BASE}/profile/client-ssl")
    persists = _items(client, f"{LTM_BASE}/persistence/cookie")
    rules = _items(client, f"{LTM_BASE}/rule")

    pool_paths = {p["fullPath"] for p in pools}
    monitor_paths = {m["fullPath"] for m in monitors}
    profile_paths = {p["fullPath"] for p in profiles}
    persist_paths = {p["fullPath"] for p in persists}
    rule_paths = {r["fullPath"] for r in rules}

    for v in virtuals:
        assert v["pool"] in pool_paths, f"virtual {v['name']} points at missing pool"
        for path in v["profiles"]:
            # System built-ins (/Common/http, /Common/tcp) aren't in our
            # fixture set; only check fixture-owned profile names.
            if path == "/Common/example_clientssl":
                assert path in profile_paths
        for path in v["persist"]:
            assert path in persist_paths, f"virtual {v['name']} → missing persist {path}"
        for path in v["rules"]:
            assert path in rule_paths, f"virtual {v['name']} → missing rule {path}"

    for p in pools:
        assert p["monitor"] in monitor_paths, f"pool {p['name']} → missing monitor"


def test_inspect_shape(client: TestClient) -> None:
    """The /inspect response wraps the Device declaration in F5's documented
    task-envelope-array shape. Both layers of wrapping are documented contract
    (ADR 007 §Prior art table). The wrapping is NOT the ADR 006 POST-body bug.
    """
    r = client.get(INSPECT_PATH)
    assert r.status_code == 200
    body = r.json()
    assert isinstance(body, list), (
        f"/inspect must return a JSON array per F5 contract; got {type(body).__name__}"
    )
    assert len(body) == 1, f"/inspect array must have exactly one element; got {len(body)}"
    entry = body[0]
    assert entry["result"]["status"] == "OK"
    assert "bigip-lab-01" in entry["selfLink"]
    assert entry["declaration"]["class"] == "DO"
    inner = entry["declaration"]["declaration"]
    assert inner["class"] == "Device"


def test_inspect_declaration_passes_adr_006_schema(client: TestClient) -> None:
    """ADR 007 §Testing strategy test (1): the load-bearing hermetic gate.

    A declaration the mock returns from /inspect must pass the same
    ADR 006 vendored-schema validator the mock enforces on POST. If this
    fails, the fixture is producing a shape the brownfield-extractor's
    schema-roundtrip test cannot accept downstream — fix the fixture, not
    the validator.
    """
    r = client.get(INSPECT_PATH)
    inner = r.json()[0]["declaration"]["declaration"]
    err = validate_do_declaration(inner)
    assert err is None, (
        f"/inspect Device declaration fails ADR 006 schema: {err}. "
        "Fix the fixture under app/fixtures/do/inspect.py, not the validator."
    )


def test_inspect_reboot_guard(client: TestClient) -> None:
    """All iControl REST handlers (LTM + extensions) share the same reboot
    guard. Covering it once on /inspect is sufficient — the guard's behavior
    is identical across routers.
    """
    client.post("/_chaos/bigip-lab-01/reset-device")  # ensures known state
    # Issue a reboot via util/bash then immediately hit /inspect.
    client.post(
        "/bigip-lab-01/mgmt/tm/util/bash",
        json={"command": "run", "utilCmdArgs": "-c reboot"},
    )
    r = client.get(INSPECT_PATH)
    assert r.status_code == 503
    assert r.headers.get("Retry-After") == "5"


def test_ltm_reboot_guard(client: TestClient) -> None:
    """Sanity check that one LTM endpoint also honors the reboot guard.
    Same guard, different router — verifying the duplication is in sync.
    """
    client.post("/_chaos/bigip-lab-01/reset-device")
    client.post(
        "/bigip-lab-01/mgmt/tm/util/bash",
        json={"command": "run", "utilCmdArgs": "-c reboot"},
    )
    r = client.get(f"{LTM_BASE}/virtual")
    assert r.status_code == 503
