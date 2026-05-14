"""Emitter unit tests.

Covers each emitter in isolation against the Checkpoint 1 mock fixtures
walked through Checkpoint 2's Walker. The three-test gate from ADR 007
§Testing strategy lives in test_three_gate.py; this file covers the
finer-grained correctness properties the gate composes from.
"""

from __future__ import annotations

import json
from typing import Any

import pytest

from brownfield.client import IControlRestClient
from brownfield.emit import emit_as3, emit_do, emit_readme, emit_terraform
from brownfield.emit._shape import (
    hostname_to_tf_identifier,
    parse_destination,
    strip_ver_query,
    tf_resource_name,
)
from brownfield.walker import Walker, WalkerOutput


@pytest.fixture
def walker_output(mock_client: IControlRestClient) -> WalkerOutput:
    """Walk the mock once; reuse the output across tests in this module."""
    return Walker(mock_client).walk_all()


# ---------- shape helpers ----------


def test_parse_destination_ipv4_standard_port() -> None:
    assert parse_destination("/Common/10.1.10.10:443") == ("10.1.10.10", 443)


def test_parse_destination_zero_address() -> None:
    assert parse_destination("/Common/0.0.0.0:80") == ("0.0.0.0", 80)


def test_parse_destination_rejects_missing_partition() -> None:
    with pytest.raises(ValueError, match="must start with"):
        parse_destination("10.1.10.10:443")


def test_parse_destination_rejects_no_port_delimiter() -> None:
    # Per ADR 007 §Out of scope: parser requires explicit :port. F5
    # destinations always include port; a port-less form is malformed
    # input the operator should hand-investigate.
    with pytest.raises(ValueError, match=r"IPv6|missing :port"):
        parse_destination("/Common/10.1.10.10")


def test_hostname_normalization_to_tf_identifier() -> None:
    assert hostname_to_tf_identifier("bigip-lab-01") == "bigip_lab_01"
    assert hostname_to_tf_identifier("bigip-dc1-042") == "bigip_dc1_042"
    # Already snake_case stays as-is.
    assert hostname_to_tf_identifier("bigip_test") == "bigip_test"


def test_tf_resource_name_composition() -> None:
    assert tf_resource_name("bigip-lab-01", "Common") == "bigip_lab_01_Common"
    assert tf_resource_name("bigip-dc1-042", "CustomTenant") == "bigip_dc1_042_CustomTenant"


def test_strip_ver_query() -> None:
    assert (
        strip_ver_query("https://bigip-lab-01/mgmt/tm/ltm/virtual?ver=17.1.0")
        == "https://bigip-lab-01/mgmt/tm/ltm/virtual"
    )
    # No query string → unchanged.
    assert strip_ver_query("https://bigip-lab-01/foo") == "https://bigip-lab-01/foo"


# ---------- AS3 emission ----------


def test_emit_as3_envelope_shape(walker_output: WalkerOutput) -> None:
    """AS3 envelope matches the project's existing template shape
    (terraform/modules/as3-declaration/templates/as3.json.tftpl):
    class:"AS3", action:"deploy", persist:True, declaration:{class:"ADC", ...}.
    """
    as3 = emit_as3(walker_output, hostname="bigip-lab-01", partition="Common")
    assert as3["class"] == "AS3"
    assert as3["action"] == "deploy"
    assert as3["persist"] is True
    decl = as3["declaration"]
    assert decl["class"] == "ADC"
    assert decl["schemaVersion"] == "3.50.0"
    assert decl["id"] == "brownfield-bigip-lab-01-Common"
    assert decl["label"] == "brownfield-bigip-lab-01"


def test_emit_as3_tenant_literal_partition_name(walker_output: WalkerOutput) -> None:
    """Per ADR 007 Addendum 2026-05-13: AS3 tenant name = F5 partition name,
    literal. The hostname disambiguates only at the Terraform layer.
    """
    as3 = emit_as3(walker_output, hostname="bigip-lab-01", partition="Common")
    tenant = as3["declaration"]["Common"]
    assert tenant["class"] == "Tenant"


def test_emit_as3_application_name_matches_partition(walker_output: WalkerOutput) -> None:
    """Application name = literal partition name per Checkpoint 3 pre-flight."""
    as3 = emit_as3(walker_output, hostname="bigip-lab-01", partition="Common")
    tenant = as3["declaration"]["Common"]
    application = tenant["Common"]  # Application keyed by partition name
    assert application["class"] == "Application"
    assert application["template"] == "generic"


def test_emit_as3_virtual_classes(walker_output: WalkerOutput) -> None:
    """Service class selection: clientssl → Service_HTTPS, http → Service_HTTP."""
    as3 = emit_as3(walker_output, hostname="bigip-lab-01", partition="Common")
    app = as3["declaration"]["Common"]["Common"]
    assert app["example_http_vs"]["class"] == "Service_HTTP"
    assert app["example_http_vs"]["virtualAddresses"] == ["10.1.10.10"]
    assert app["example_http_vs"]["virtualPort"] == 80
    assert app["example_https_vs"]["class"] == "Service_HTTPS"
    assert app["example_https_vs"]["virtualPort"] == 443
    assert app["example_https_vs"]["serverTLS"] == "example_clientssl"


def test_emit_as3_pool_with_members_and_monitor_ref(walker_output: WalkerOutput) -> None:
    """Pool gets members from walker's _members embed, monitor as a
    simple-name reference within the application.
    """
    as3 = emit_as3(walker_output, hostname="bigip-lab-01", partition="Common")
    app = as3["declaration"]["Common"]["Common"]
    pool = app["example_pool"]
    assert pool["class"] == "Pool"
    assert pool["loadBalancingMode"] == "round-robin"
    assert pool["monitors"] == ["example_http_monitor"]
    assert len(pool["members"]) == 3
    # First two members are enabled, third is disabled per the fixture.
    enable_flags = [m["enable"] for m in pool["members"]]
    assert enable_flags == [True, True, False]


def test_emit_as3_monitor_recv_field_renamed(walker_output: WalkerOutput) -> None:
    """ACC mapping: REST `recv` → AS3 `receive`."""
    as3 = emit_as3(walker_output, hostname="bigip-lab-01", partition="Common")
    app = as3["declaration"]["Common"]["Common"]
    monitor = app["example_http_monitor"]
    assert monitor["class"] == "Monitor"
    assert monitor["monitorType"] == "http"
    assert "receive" in monitor  # renamed from recv
    assert "/health" in monitor["send"]  # custom send preserved


def test_emit_as3_irule_body_verbatim(walker_output: WalkerOutput) -> None:
    """iRule TCL body passes through unchanged into AS3 iRule class."""
    as3 = emit_as3(walker_output, hostname="bigip-lab-01", partition="Common")
    app = as3["declaration"]["Common"]["Common"]
    rule = app["example_irule"]
    assert rule["class"] == "iRule"
    assert "when HTTP_REQUEST" in rule["iRule"]
    assert "\n" in rule["iRule"]  # multi-line preserved


# ---------- DO emission ----------


def test_emit_do_returns_device_class(walker_output: WalkerOutput) -> None:
    do = emit_do(walker_output, hostname="bigip-lab-01")
    assert do["class"] == "Device"
    assert do["schemaVersion"] == "1.40.0"


def test_emit_do_carries_provenance_label(walker_output: WalkerOutput) -> None:
    do = emit_do(walker_output, hostname="bigip-lab-01")
    assert do["label"] == "brownfield extraction of bigip-lab-01"


def test_emit_do_does_not_mutate_walker_output(walker_output: WalkerOutput) -> None:
    """emit_do returns a new dict — re-running with the same walker_output
    must produce the same result."""
    do1 = emit_do(walker_output, hostname="bigip-lab-01")
    do2 = emit_do(walker_output, hostname="bigip-lab-01")
    assert do1 == do2


# ---------- Terraform emission ----------


def test_emit_terraform_returns_both_files() -> None:
    files = emit_terraform(hostname="bigip-lab-01", partition="Common")
    assert set(files.keys()) == {"main.tf", "imports.tf"}


def test_emit_terraform_main_tf_has_both_resources() -> None:
    files = emit_terraform(hostname="bigip-lab-01", partition="Common")
    main_tf = files["main.tf"]
    assert 'resource "bigip_as3" "bigip_lab_01_Common"' in main_tf
    assert 'resource "bigip_do" "bigip_lab_01_Common"' in main_tf
    assert "F5Networks/bigip" in main_tf  # provider source pin


def test_emit_terraform_imports_tf_has_as3_only() -> None:
    """ADR 007 apply-no-op adoption: bigip_as3 gets an import block;
    bigip_do does NOT. The DO adoption flow is handled by first apply.

    Asserts absence of the import-block target `bigip_do.<name>` rather
    than the bare string `bigip_do`, since the imports.tf comment
    legitimately mentions bigip_do to direct readers at main.tf for
    the apply-no-op rationale.
    """
    files = emit_terraform(hostname="bigip-lab-01", partition="Common")
    imports_tf = files["imports.tf"]
    assert "import {" in imports_tf
    assert "to = bigip_as3.bigip_lab_01_Common" in imports_tf
    assert 'id = "Common"' in imports_tf
    # No import block targeting bigip_do — apply-no-op adoption flow.
    assert "to = bigip_do." not in imports_tf


def test_emit_terraform_is_deterministic() -> None:
    """Identical inputs produce identical bytes (byte-stability)."""
    a = emit_terraform(hostname="bigip-lab-01", partition="Common")
    b = emit_terraform(hostname="bigip-lab-01", partition="Common")
    assert a == b


# ---------- README emission ----------


def test_emit_readme_contains_extraction_summary(walker_output: WalkerOutput) -> None:
    md = emit_readme(walker_output, hostname="bigip-lab-01", partition="Common")
    assert "bigip-lab-01" in md
    assert "/Common" in md
    # Counts present.
    assert "2 virtual server(s)" in md
    assert "1 pool(s)" in md
    assert "3 total members" in md
    assert "1 iRule(s)" in md


def test_emit_readme_is_deterministic(walker_output: WalkerOutput) -> None:
    """Re-running emit_readme on the same walker output produces identical
    bytes. Documents the byte-stability property in the README itself.
    """
    a = emit_readme(walker_output, hostname="bigip-lab-01", partition="Common")
    b = emit_readme(walker_output, hostname="bigip-lab-01", partition="Common")
    assert a == b


def test_emit_readme_has_no_runtime_timestamp_phrases(walker_output: WalkerOutput) -> None:
    """Per Checkpoint 3 discipline: README must produce stable output
    across runs of identical device state.

    `test_emit_readme_is_deterministic` is the load-bearing test (byte
    equality across runs). This test adds a guard against the specific
    phrasings that have historically introduced timestamps — making
    intent explicit so a future "improvement" that adds a timestamp
    fails loudly here as well as on the determinism check.

    Static ADR date references (e.g. "Addendum 2026-05-13") are
    deterministic — they're checked-in copy that doesn't change between
    runs. The phrases below are dynamic-only.
    """
    md = emit_readme(walker_output, hostname="bigip-lab-01", partition="Common")
    assert "Generated on " not in md
    assert "Generated at " not in md
    # The tool's pinned version IS allowed (deterministic per release).
    assert "brownfield " in md


def test_emit_readme_cites_adr_007_and_006() -> None:
    """The README documents the adoption flow — it must point at the
    ADRs that define the contract."""
    # Use an empty WalkerOutput so the test doesn't depend on the mock fixture.
    md = emit_readme(WalkerOutput(), hostname="bigip-lab-01", partition="Common")
    assert "ADR 007" in md
    assert "ADR 006" in md
    assert "ACC" in md
    assert "e6f9fcec" in md  # ACC commit hash provenance


# ---------- builtin filter integration ----------


def test_emit_as3_excludes_builtins_from_emitted_objects() -> None:
    """Discipline requirement from Checkpoint 3 pre-flight: nothing on
    the BIGIP_BUILTINS list ever appears in emitted AS3 output when
    partition=='Common'. Constructed walker output containing the
    built-in `/Common/http` monitor — the filter must drop it.
    """
    builtin_monitor: dict[str, Any] = {
        "partition": "Common",
        "fullPath": "/Common/http",
        "name": "http",
        "interval": 5,
        "timeout": 16,
        "send": "GET /\r\n",
        "recv": "",
    }
    operator_monitor: dict[str, Any] = {
        "partition": "Common",
        "fullPath": "/Common/example_http_monitor",
        "name": "example_http_monitor",
        "interval": 5,
        "timeout": 16,
        "send": "GET /health\r\n",
        "recv": "HTTP/1.",
    }
    output = WalkerOutput(monitors_http=[builtin_monitor, operator_monitor])
    as3 = emit_as3(output, hostname="bigip-lab-01", partition="Common")
    app = as3["declaration"]["Common"]["Common"]
    assert "http" not in app  # built-in filtered out
    assert "example_http_monitor" in app  # operator content preserved


# ---------- json/HCL stability when written ----------


def _stable_serialize_check(value: Any, *, iterations: int = 3) -> None:
    """Round-trip JSON serialization N times and assert byte equality."""
    serialized = [json.dumps(value, sort_keys=True, indent=2) for _ in range(iterations)]
    assert len(set(serialized)) == 1


def test_emit_as3_json_serialization_is_byte_stable(walker_output: WalkerOutput) -> None:
    """JSON serialization is deterministic on identical inputs."""
    as3 = emit_as3(walker_output, hostname="bigip-lab-01", partition="Common")
    _stable_serialize_check(as3)


def test_emit_do_json_serialization_is_byte_stable(walker_output: WalkerOutput) -> None:
    do = emit_do(walker_output, hostname="bigip-lab-01")
    _stable_serialize_check(do)
