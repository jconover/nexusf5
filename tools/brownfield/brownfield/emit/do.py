"""DO declaration emitter.

The walker already does the heavy lifting for DO: it unwraps F5's
`/inspect` task envelope + class:"DO" wrapper and returns the inner
`class: "Device"` block directly (walker.walk_inspect()). The emitter's
job is light: pass the declaration through with deterministic field
ordering and an extraction provenance label.

ADR 006 schema gate applies: the emitted declaration must validate
against the vendored DO 1.47.0 base schema. Verified by the
test_emit_do_passes_adr_006_schema test in tests/test_emit.py.
"""

from __future__ import annotations

from typing import Any

from brownfield.walker import WalkerOutput


def emit_do(walker_output: WalkerOutput, *, hostname: str) -> dict[str, Any]:
    """Build a DO declaration matching the device's current state.

    The walker's `inspect` field is already the inner Device declaration.
    We pass it through with a label set so apply-time logs identify the
    declaration's origin ("brownfield extraction of <hostname>").

    Returns a new dict; does not mutate walker_output.inspect.
    """
    device = dict(walker_output.inspect)
    # Provenance label — apply-time logs and BIG-IP UI surface this.
    # Set unconditionally even if /inspect carried a label; brownfield
    # extraction is the authoritative origin for declarations we emit.
    device["label"] = f"brownfield extraction of {hostname}"
    return device
