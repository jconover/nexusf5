"""The three-test gate from ADR 007 §Scope of the first cut.

Per ADR 007:
  1. Schema validation: every emitted declaration passes ADR 006 validators.
  2. terraform plan exit 0: generated import blocks + extracted declarations
     produce zero-diff Terraform plan.
  3. Re-extraction round-trip: extract → apply via bigip_as3 → re-extract
     → byte-stable up to documented normalization.

Test scope per Checkpoint 3 pre-flight:

  - Test 1 (schema validation): run emitted AS3 and DO through the same
    vendored ADR 006 validators the mock enforces on POST. Hermetic,
    fast, the load-bearing correctness gate.

  - Test 2 (terraform plan equivalent): real `terraform plan` requires
    the bigip provider + a live device. Out of reach for hermetic unit
    tests. The achievable surrogate: POST the emitted AS3 declaration
    to the mock's /mgmt/shared/appsvcs/declare/{tenant} endpoint and
    assert it's accepted. The mock's POST validates against the
    ADR 006 schema at the root level — same gate the F5 provider's
    pre-apply check uses. Real-terraform-plan testing waits for the
    optional end-of-Phase-5 cloud round-trip per ADR 007 §Scope.

  - Test 3 (re-extraction byte-stability): the most demanding. Extract
    → emit → POST to mock → re-walk → re-emit → assert declarations are
    byte-stable. The mock's POST-doesn't-mutate-/ltm/* property
    (mock-vs-real-F5 limitation) makes this an apply-no-op-stability
    test in practice — which IS exactly the apply-no-op adoption
    property ADR 007 §Decision is built on. Real-apply-then-re-extract
    testing also waits for the optional cloud round-trip.

When the cloud round-trip lands, tests 2 and 3 get a parallel
real-F5 version. The mock-based versions stay as the fast inner-loop
gate.
"""

from __future__ import annotations

import json

from app.schemas import validate_as3_declaration, validate_do_declaration

from brownfield.client import IControlRestClient
from brownfield.emit import emit_as3, emit_do
from brownfield.walker import Walker

# ---------- Gate Test 1: ADR 006 schema validation ----------


def test_gate_1_emitted_as3_passes_adr_006_schema(
    mock_client: IControlRestClient,
) -> None:
    """The load-bearing correctness gate: emitter output validates
    against the same vendored AS3 3.51.0 schema the mock enforces.

    The mock-f5 validator is root-level only per ADR 006 §Scope of the
    first cut — it catches `class` discriminator errors, allowed
    properties, schemaVersion enum. That's the largest bug class.
    Deeper validation comes from real F5; covered by the optional
    cloud round-trip per ADR 007.
    """
    walker_output = Walker(mock_client).walk_all()
    as3 = emit_as3(walker_output, hostname="bigip-lab-01", partition="Common")
    err = validate_as3_declaration(as3)
    assert err is None, (
        f"Emitted AS3 fails ADR 006 schema: {err}. "
        "Either the emitter is producing the wrong root shape, or the "
        "vendored schema regressed — fix the emitter unless the schema "
        "itself was refreshed."
    )


def test_gate_1_emitted_do_passes_adr_006_schema(
    mock_client: IControlRestClient,
) -> None:
    """Same gate at the DO layer: emitter output validates against the
    vendored DO 1.47.0 schema."""
    walker_output = Walker(mock_client).walk_all()
    do = emit_do(walker_output, hostname="bigip-lab-01")
    err = validate_do_declaration(do)
    assert err is None, (
        f"Emitted DO fails ADR 006 schema: {err}. "
        "The walker's /inspect unwrapping already validates; if the "
        "emitter broke it, fix emit_do() not the validator."
    )


# ---------- Gate Test 2: terraform plan equivalent (POST to mock) ----------


def test_gate_2_emitted_as3_accepted_by_mock_post(
    mock_client: IControlRestClient,
) -> None:
    """Hermetic surrogate for `terraform plan -detailed-exitcode == 0`:
    POST the emitted AS3 to the mock's /declare/{tenant} endpoint and
    assert acceptance. The mock validates against the same ADR 006
    schema the F5 provider's pre-apply check uses, so acceptance here
    is the strongest hermetic proxy for "real F5 would also accept."
    """
    walker_output = Walker(mock_client).walk_all()
    as3 = emit_as3(walker_output, hostname="bigip-lab-01", partition="Common")

    # The mock's AS3 POST endpoint is at /mgmt/shared/appsvcs/declare/{tenant}.
    # We re-use the http_client from mock_client (a TestClient bound to
    # the in-process mock-f5 app) for raw POST access.
    resp = mock_client._client.post(  # type: ignore[attr-defined]
        "/mgmt/shared/appsvcs/declare/Common",
        json=as3,
    )
    assert resp.status_code == 202, (
        f"Mock rejected emitted AS3 with HTTP {resp.status_code}: "
        f"{resp.text[:500]}. The emitter is producing a shape real F5 "
        "would also reject — fix the emitter."
    )


def test_gate_2_emitted_do_accepted_by_mock_post(
    mock_client: IControlRestClient,
) -> None:
    """Same gate at the DO layer."""
    walker_output = Walker(mock_client).walk_all()
    do = emit_do(walker_output, hostname="bigip-lab-01")
    resp = mock_client._client.post(  # type: ignore[attr-defined]
        "/mgmt/shared/declarative-onboarding",
        json=do,
    )
    assert resp.status_code == 202, (
        f"Mock rejected emitted DO with HTTP {resp.status_code}: "
        f"{resp.text[:500]}. The emitter is producing a shape real F5 "
        "would also reject — fix the emitter."
    )


# ---------- Gate Test 3: Re-extraction byte-stability ----------


def test_gate_3_re_extraction_byte_stable_as3(
    mock_client: IControlRestClient,
) -> None:
    """Extract → emit → POST → re-walk → re-emit → byte-stable.

    Documents the apply-no-op adoption property: emitting a declaration
    from extracted state and applying it back must not change what a
    subsequent extraction sees. Under the mock (POST doesn't mutate
    /ltm/*), this reduces to emitter determinism plus walker stability
    — both of which are independently testable but compose here into
    the contract ADR 007 §Scope names.
    """
    # First extract → emit
    walker_output_1 = Walker(mock_client).walk_all()
    as3_1 = emit_as3(walker_output_1, hostname="bigip-lab-01", partition="Common")
    as3_1_bytes = json.dumps(as3_1, sort_keys=True, indent=2)

    # POST to mock (the apply-no-op step)
    resp = mock_client._client.post(  # type: ignore[attr-defined]
        "/mgmt/shared/appsvcs/declare/Common",
        json=as3_1,
    )
    assert resp.status_code == 202

    # Re-extract → emit
    walker_output_2 = Walker(mock_client).walk_all()
    as3_2 = emit_as3(walker_output_2, hostname="bigip-lab-01", partition="Common")
    as3_2_bytes = json.dumps(as3_2, sort_keys=True, indent=2)

    # Byte-stable up to documented normalization (which is built into
    # the emitter — sort_keys, deterministic ordering, no timestamps).
    assert as3_1_bytes == as3_2_bytes, (
        "Re-extracted AS3 differs from original. Either walker output "
        "drifted (mock state mutated unexpectedly) or emitter is "
        "non-deterministic — investigate both."
    )


def test_gate_3_re_extraction_byte_stable_do(
    mock_client: IControlRestClient,
) -> None:
    """Same byte-stability gate at the DO layer."""
    walker_output_1 = Walker(mock_client).walk_all()
    do_1 = emit_do(walker_output_1, hostname="bigip-lab-01")
    do_1_bytes = json.dumps(do_1, sort_keys=True, indent=2)

    resp = mock_client._client.post(  # type: ignore[attr-defined]
        "/mgmt/shared/declarative-onboarding",
        json=do_1,
    )
    assert resp.status_code == 202

    walker_output_2 = Walker(mock_client).walk_all()
    do_2 = emit_do(walker_output_2, hostname="bigip-lab-01")
    do_2_bytes = json.dumps(do_2, sort_keys=True, indent=2)

    assert do_1_bytes == do_2_bytes


# ---------- Composition: all three layers together ----------


def test_full_pipeline_extract_emit_validate_post(
    mock_client: IControlRestClient,
) -> None:
    """End-to-end smoke: extract → emit AS3+DO → schema-validate both →
    POST both to mock → assert all green. This is the Checkpoint 3
    close-out integration confidence test.
    """
    walker_output = Walker(mock_client).walk_all()
    as3 = emit_as3(walker_output, hostname="bigip-lab-01", partition="Common")
    do = emit_do(walker_output, hostname="bigip-lab-01")

    # Schema gate
    assert validate_as3_declaration(as3) is None
    assert validate_do_declaration(do) is None

    # POST gate
    as3_resp = mock_client._client.post(  # type: ignore[attr-defined]
        "/mgmt/shared/appsvcs/declare/Common", json=as3
    )
    assert as3_resp.status_code == 202
    do_resp = mock_client._client.post(  # type: ignore[attr-defined]
        "/mgmt/shared/declarative-onboarding", json=do
    )
    assert do_resp.status_code == 202
