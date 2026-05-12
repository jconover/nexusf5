"""Schema validation for DO + AS3 declaration bodies posted to the mock.

The mock impersonates F5 BIG-IP's iControl REST surface. A declaration that
real F5 DO 1.47.0 or AS3 3.51.0 would reject must also be rejected here —
otherwise the mock trains downstream code (terraform templates, test
fixtures) on shapes that fail in production. PR 3 iteration 8 surfaced
exactly this: a `class: "DO"` outer wrapper in the do-declaration template
was accepted by the mock for months, then rejected by a real BIG-IP on the
first cloud round-trip. See `docs/decisions/006-mock-contract-fidelity.md`.

Validation runs against the pinned schemas under `mock-f5/schemas/`. Scope
is intentionally root-level (the `class` discriminator, allowlisted
properties, schemaVersion enum) — that's what catches the bug class that
escaped to production. Inner `$ref`s (`system.schema.json`,
`network.schema.json`, AS3 sub-schemas) resolve to a permissive empty
schema today; expand the vendored tree + tighten the resolver if a future
bug surfaces at an inner level. The README in `schemas/` documents this
incremental scope.

Validation errors are formatted to match the response shape real F5 DO/AS3
returns on a 400 — same `errors` array structure (keyword, dataPath,
schemaPath, params, message), so a caller (terraform-provider-bigip, ad-hoc
curl) sees the same surface.
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

from jsonschema import Draft7Validator
from jsonschema.exceptions import ValidationError
from referencing import Registry, Resource
from referencing.jsonschema import DRAFT7

SCHEMAS_DIR = Path(__file__).resolve().parent.parent / "schemas"

DO_SCHEMA_PATH = SCHEMAS_DIR / "do" / "v1.47.0" / "base.schema.json"
AS3_SCHEMA_PATH = SCHEMAS_DIR / "as3" / "v3.51.0" / "as3-request-schema.json"

# Empty Draft-7 resource returned for any unresolved `$ref`. Equivalent to
# "no constraints" — descended-into properties validate freely. The
# specification has to be declared explicitly because `Resource.from_contents`
# on `{}` cannot autodetect the JSON Schema dialect.
_PERMISSIVE_RESOURCE = DRAFT7.create_resource({})


def _permissive_retrieve(uri: str) -> Resource[Any]:
    """Resolve any unknown `$ref` URI to a permissive empty Draft-7 schema.

    We vendor only the root schemas (see schemas/README.md "Scope of
    validation"). Sub-schema `$ref`s — `system.schema.json`,
    `network.schema.json`, AS3 sub-schemas — would otherwise raise
    `Unresolvable` mid-validation. Pass-through is the deliberate trade:
    root-level shape is enforced, inner-class details are not. Tighten
    by vendoring the referenced schemas + dropping this retriever when
    a bug surfaces below the root.
    """
    return _PERMISSIVE_RESOURCE


_REGISTRY: Registry[Any] = Registry(retrieve=_permissive_retrieve)  # type: ignore[call-arg]


@lru_cache(maxsize=4)
def _load_validator(schema_path: Path) -> Draft7Validator:
    schema = json.loads(schema_path.read_text())
    return Draft7Validator(schema, registry=_REGISTRY)


def _format_f5_error(errors: list[ValidationError], pinned_version: str) -> dict[str, Any]:
    """Format jsonschema errors into the F5 DO/AS3 400 response shape.

    Real F5 returns a body like:
        {"code": 400, "status": "ERROR", "message": "bad declaration",
         "errors": [{"keyword": "...", "dataPath": "...",
                     "schemaPath": "...", "params": {...},
                     "message": "..."}, ...]}
    Matching that shape lets the terraform-provider-bigip's error parser
    surface the same diagnostic against the mock as it would against real
    F5. Also lets the validator-self-test in ADR 006 / make-test-self-test
    compare the mock's response to the recorded iter-9 response by shape.
    """
    formatted = []
    for err in errors:
        params = {"validator_value": err.validator_value} if err.validator_value is not None else {}
        formatted.append(
            {
                "keyword": err.validator,
                "dataPath": "/" + "/".join(str(p) for p in err.absolute_path),
                "schemaPath": "#/" + "/".join(str(p) for p in err.absolute_schema_path),
                "params": params,
                "message": err.message,
            }
        )
    return {
        "code": 400,
        "status": "ERROR",
        "message": "bad declaration",
        "errors": formatted,
        "schemaPinnedVersion": pinned_version,
    }


def validate_do_declaration(body: dict[str, Any]) -> dict[str, Any] | None:
    """Return None if `body` validates against F5 DO v1.47.0 base schema.

    Returns an F5-shape error response dict if it doesn't. Caller is expected
    to return that dict with HTTP 400. The DO schema's root requires
    `class: "Device"` (const) — this catches the bug 7 class of error
    (wrong outer wrapper).
    """
    validator = _load_validator(DO_SCHEMA_PATH)
    errors = sorted(validator.iter_errors(body), key=lambda e: list(e.absolute_path))
    if not errors:
        return None
    return _format_f5_error(errors, pinned_version="DO v1.47.0")


def validate_as3_declaration(body: dict[str, Any]) -> dict[str, Any] | None:
    """Return None if `body` validates against F5 AS3 v3.51.0 request schema.

    Returns an F5-shape error response dict if it doesn't. AS3's root schema
    uses `oneOf` between direct ADC, ADC_Array, AS3 wrapper, and patch
    shapes — passing any one branch is acceptance.
    """
    validator = _load_validator(AS3_SCHEMA_PATH)
    errors = sorted(validator.iter_errors(body), key=lambda e: list(e.absolute_path))
    if not errors:
        return None
    return _format_f5_error(errors, pinned_version="AS3 v3.51.0")
