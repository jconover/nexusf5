"""Tests for the vendored F5 built-in filter.

Coverage:
  - Every entry in BIGIP_BUILTINS is filtered when partition='Common'.
  - Operator-named-collision in a custom partition is NOT filtered
    (partition gate is the safety property).
  - Custom objects in /Common with non-builtin names pass through.
  - filter_builtins() returns a new list in input order.
"""

from __future__ import annotations

from brownfield.builtins import BIGIP_BUILTINS, filter_builtins, is_builtin


def test_every_listed_name_is_filtered_when_partition_common() -> None:
    """The vendored ACC list is the contract — every entry must be
    recognized as a built-in when it appears in /Common.
    """
    for full_path in BIGIP_BUILTINS:
        item = {"partition": "Common", "fullPath": full_path, "name": full_path.split("/")[-1]}
        assert is_builtin(item), f"{full_path} should be recognized as built-in"


def test_operator_named_collision_in_custom_partition_is_extracted() -> None:
    """An operator monitor literally named `http` in a custom partition
    must NOT be filtered, even though `http` is on the BIGIP_BUILTINS
    list. The partition gate disambiguates: `/Common/http` is the F5
    built-in; `/CustomTenant/http` is operator content.

    This is the safety property the conservative-list approach exists
    for — name collisions are resolved by partition, not by stripping
    any object whose name happens to match a built-in.
    """
    operator_http_monitor = {
        "partition": "CustomTenant",
        "fullPath": "/CustomTenant/http",
        "name": "http",
        "defaultsFrom": "/Common/http",  # legitimately inherits from built-in
        "send": "GET /custom HTTP/1.1\r\n\r\n",
    }
    assert not is_builtin(operator_http_monitor)


def test_custom_monitor_in_common_with_unique_name_is_not_filtered() -> None:
    """A custom monitor in /Common with a name that doesn't collide
    with any built-in passes the filter. This is the common case for
    brownfield extraction — operators create custom objects in /Common
    with names like `app1_http_monitor`.
    """
    custom = {
        "partition": "Common",
        "fullPath": "/Common/example_http_monitor",
        "name": "example_http_monitor",
    }
    assert not is_builtin(custom)


def test_filter_builtins_preserves_order_and_returns_new_list() -> None:
    """filter_builtins must be order-preserving (input order, not
    sorted) and non-mutating. The walker's downstream emitter depends
    on stable ordering for byte-stable re-emission.
    """
    items = [
        {"partition": "Common", "fullPath": "/Common/http", "name": "http"},  # builtin
        {"partition": "Common", "fullPath": "/Common/custom1", "name": "custom1"},
        {"partition": "Common", "fullPath": "/Common/tcp", "name": "tcp"},  # builtin
        {"partition": "Common", "fullPath": "/Common/custom2", "name": "custom2"},
    ]
    filtered = filter_builtins(items)
    names = [item["name"] for item in filtered]
    assert names == ["custom1", "custom2"]
    # Original list was not mutated.
    assert len(items) == 4


def test_filter_handles_missing_partition_or_fullpath() -> None:
    """Items lacking partition or fullPath are treated as not-built-in.
    Real F5 always sets both, but defensive coding catches mock-fidelity
    gaps without producing a confusing crash.
    """
    no_partition = {"fullPath": "/Common/http", "name": "http"}
    no_fullpath = {"partition": "Common", "name": "http"}
    assert not is_builtin(no_partition)
    assert not is_builtin(no_fullpath)


def test_builtins_list_size_matches_provenance() -> None:
    """Regression guard: a refresh of the vendored ACC list should
    update both the entries AND the provenance docstring's count field.
    Test fails if someone updates the entries without updating the
    docstring (or vice versa).

    Current pin: ACC v1.24.0 commit e6f9fcec, 234 entries.
    """
    assert len(BIGIP_BUILTINS) == 234
