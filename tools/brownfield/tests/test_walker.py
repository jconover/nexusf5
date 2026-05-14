"""Walker tests against the in-process mock-f5 app.

Coverage:
  - Each per-endpoint walk method returns the documented items shape
    with the F5 collection envelope stripped.
  - `walk_pools(include_members=True)` follows the membersReference link
    and embeds members under `_members`.
  - `walk_inspect()` unwraps F5's task-envelope + class:"DO" wrapping
    and returns the inner `class: "Device"` block.
  - **ADR-006 composition gate.** The walker's `walk_inspect()` output
    is a Device declaration — it must pass the same ADR 006 vendored
    schema validator the mock enforces on POST. This is the load-bearing
    test per ADR 007 §Testing strategy applied at the walker layer.
  - `walk_all()` returns a complete WalkerOutput with every field
    populated as expected for the Checkpoint 1 fixture set.
  - Shape-mismatch path: a malformed /inspect response raises ValueError
    rather than silently producing a broken declaration.
"""

from __future__ import annotations

import pytest
from app.schemas import validate_do_declaration

from brownfield.client import IControlRestClient
from brownfield.walker import Walker, WalkerOutput


def test_walk_virtuals_strips_envelope(mock_client: IControlRestClient) -> None:
    items = Walker(mock_client).walk_virtuals()
    names = {v["name"] for v in items}
    assert names == {"example_http_vs", "example_https_vs"}
    # Envelope stripped: each item is a dict (not the kind/selfLink/items wrapper).
    for v in items:
        assert "items" not in v
        assert v.get("kind") == "tm:ltm:virtual:virtualstate"


def test_walk_pools_embeds_members(mock_client: IControlRestClient) -> None:
    pools = Walker(mock_client).walk_pools()
    assert len(pools) == 1
    pool = pools[0]
    assert pool["fullPath"] == "/Common/example_pool"
    # _members is the walker's added key; verifies membersReference was followed.
    members = pool["_members"]
    assert len(members) == 3
    member_addrs = {m["address"] for m in members}
    assert member_addrs == {"10.1.20.10", "10.1.20.11", "10.1.20.12"}


def test_walk_pools_without_members(mock_client: IControlRestClient) -> None:
    pools = Walker(mock_client).walk_pools(include_members=False)
    assert "_members" not in pools[0]
    # The membersReference link itself is preserved for caller-driven follow-up.
    assert "link" in pools[0]["membersReference"]


def test_walk_monitors_http(mock_client: IControlRestClient) -> None:
    mons = Walker(mock_client).walk_monitors_http()
    assert len(mons) == 1
    assert mons[0]["fullPath"] == "/Common/example_http_monitor"
    # send preserved verbatim — emission decides what to do with it.
    assert "/health" in mons[0]["send"]


def test_walk_profiles_clientssl(mock_client: IControlRestClient) -> None:
    profs = Walker(mock_client).walk_profiles_clientssl()
    assert len(profs) == 1
    assert profs[0]["fullPath"] == "/Common/example_clientssl"
    assert profs[0]["certKeyChain"][0]["cert"] == "/Common/example.crt"


def test_walk_persistence_cookie(mock_client: IControlRestClient) -> None:
    persists = Walker(mock_client).walk_persistence_cookie()
    assert len(persists) == 1
    assert persists[0]["fullPath"] == "/Common/cookie_persist"
    assert persists[0]["cookieName"] == "SERVERID"


def test_walk_rules(mock_client: IControlRestClient) -> None:
    rules = Walker(mock_client).walk_rules()
    assert len(rules) == 1
    # iRule TCL body preserved verbatim including newlines.
    body = rules[0]["apiAnonymous"]
    assert "when HTTP_REQUEST" in body
    assert "\n" in body


def test_walk_inspect_unwraps_to_device(mock_client: IControlRestClient) -> None:
    device = Walker(mock_client).walk_inspect()
    # Walker stripped: outer task envelope (id/selfLink/result), outer
    # class:"DO" wrapper. Returned dict is the inner Device declaration.
    assert device["class"] == "Device"
    assert "schemaVersion" in device
    assert "Common" in device
    # Confirm the unwrapping didn't keep envelope artifacts.
    assert "result" not in device
    assert "id" not in device


def test_walk_inspect_passes_adr_006_schema(mock_client: IControlRestClient) -> None:
    """ADR-006 composition gate at the walker layer.

    The walker's `walk_inspect()` produces a Device declaration. That
    declaration must validate against the same vendored DO 1.47.0 schema
    the mock enforces on POST. If this fails, either the walker's
    unwrapping is dropping fields it shouldn't, or the mock fixture
    regressed — both are bugs surfaced loudly here rather than emerging
    downstream when the emitter tries to ship the broken shape.
    """
    device = Walker(mock_client).walk_inspect()
    err = validate_do_declaration(device)
    assert err is None, (
        f"Walker's /inspect output fails ADR 006 schema: {err}. "
        "Either walker.walk_inspect() unwrapping is wrong, or the mock "
        "fixture (app/fixtures/do/inspect.py) regressed."
    )


def test_walk_all_populates_every_field(mock_client: IControlRestClient) -> None:
    """End-to-end smoke test: a single walk_all() against the Checkpoint 1
    fixture set populates every WalkerOutput field with realistic data.
    """
    out = Walker(mock_client).walk_all()
    assert isinstance(out, WalkerOutput)
    assert len(out.virtuals) == 2
    assert len(out.pools) == 1
    assert len(out.pools[0]["_members"]) == 3
    assert len(out.monitors_http) == 1
    assert len(out.profiles_clientssl) == 1
    assert len(out.persistence_cookie) == 1
    assert len(out.rules) == 1
    assert out.inspect["class"] == "Device"


def test_walk_inspect_rejects_malformed_response() -> None:
    """A /inspect response that lacks the documented double-wrapping
    must raise ValueError rather than silently producing a broken
    declaration. Simulates either a mock regression or a real-F5 doc
    divergence.
    """

    class _BrokenClient:
        def get(self, _path: str) -> object:
            # Missing the inner declaration.class: "Device" — should reject.
            return [{"id": 0, "result": {"status": "OK"}, "declaration": {"class": "DO"}}]

    walker = Walker(_BrokenClient())  # type: ignore[arg-type]
    with pytest.raises(ValueError, match=r"Device|inner"):
        walker.walk_inspect()
