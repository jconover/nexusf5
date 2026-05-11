# ADR 006 — Mock contract fidelity: validate against vendor schemas

- Date: 2026-05-11
- Status: Accepted

## Context

The mock iControl REST server (`mock-f5/`) lets the full upgrade pipeline
run end-to-end on a laptop with no real BIG-IP. `make test` exercises the
mock; `make integration` and `make integration-immutable` exercise a real
AWS BIG-IP VE. The mock's job is to faithfully impersonate F5 BIG-IP's
HTTP surface — wire-shaped enough that anything passing the mock passes
real BIG-IP.

Phase 4 PR 3 surfaced a load-bearing failure of that contract. The
do-declaration module's template (`terraform/modules/do-declaration/
templates/do.json.tftpl`) had been emitting a declaration wrapped in a
`class: "DO"` envelope since PR 1. F5 DO's actual API requires `class:
"Device"` at the root (confirmed against `base.schema.json` in
`f5-declarative-onboarding v1.47.0`; against F5's own examples in
`f5-declarative-onboarding/examples/onboard.json` and
`f5-bigip-runtime-init/examples/runtime_configs/full_example_aws_1nic.yaml`;
and against `terraform-provider-bigip v1.26.0`'s own
`examples/bigip_onboard.tf`). The mock had been accepting the wrapper
shape for months because the mock's `do_post` handler treated the body as
opaque JSON ("Permissive ingress is fine because the mock's job is to
round-trip the body, not to validate F5 schema"). The closed loop:

- Template emits wrong shape.
- Mock accepts wrong shape.
- Mock's own test fixture (`test_do.py::MIN_DECL`) uses wrong shape.
- The fixture's success "trains" the mock.
- Local `make test` is green.
- Lab env's `terraform apply` is green (it points at the mock).
- First cloud round-trip rejects the shape with HTTP 400.

PR 3 spent **three cloud iterations** (iter-7, iter-8, iter-9) chasing this
miscalibration — including one round where a "fix" to the inner declaration
left the outer wrapper in place and re-hit the same error with a different
proximate cause in the wrapper's outer schemaVersion field. The cost was
small in dollars (~$0.30) but expensive in iteration-time and attention.
A schema-faithful mock would have failed `make test` immediately on
iter-1 with no AWS spend.

## Decision

Mock endpoints that accept F5 declarations validate request bodies against
the corresponding published vendor JSON schema before accepting them. A
declaration that real F5 would reject with HTTP 400 is rejected here with
the same HTTP 400 + an F5-shape error response.

Three coordinated commitments:

1. **Schemas are vendored under `mock-f5/schemas/`** with explicit
   version-pinned directories (`schemas/do/v1.47.0/`,
   `schemas/as3/v3.51.0/`). Each file is fetched from the matching upstream
   release tag and cited in `schemas/README.md` with the canonical GitHub
   URL. Refreshes are explicit version bumps, not automatic.

2. **Validation runs in the POST handler**, between body parse and task
   start (`mock-f5/app/routers/extensions.py`,
   `mock-f5/app/schemas.py::validate_{do,as3}_declaration`). Validation
   errors return the same response shape real F5 returns (`code`, `status`,
   `message`, `errors` array with `keyword`/`dataPath`/`schemaPath`/`params`/
   `message`), so `terraform-provider-bigip`'s error parser surfaces the
   same diagnostic against the mock as it would against real F5.

3. **Mock test fixtures (`MIN_DECL`, `bad_decl`, `good_decl`, etc.) are
   valid under those schemas.** A fixture that fails the new validator at
   `make test` time gets fixed at the fixture, not by relaxing the
   validator. The fixture is part of the contract.

## Scope of the first cut

The vendored schemas are **root-level only**: `base.schema.json` for DO,
`as3-request-schema.json` for AS3. Both schemas internally `$ref`
sub-schemas (`system.schema.json`, `network.schema.json`, AS3 sub-schemas)
that are not yet vendored. The validator's `referencing.Registry` returns
an empty permissive resource for any unresolved `$ref`, so root-level
constraints (`class` const, `additionalProperties: false`, `schemaVersion`
enum) fire while inner-class details validate freely.

This is intentional and minimal: the bug class that took down PR 3 was a
root-level shape error, and root-level validation closes that class. When
the next bug surfaces below the root, the path forward is:

1. Vendor the referenced sub-schemas under the same version-pinned
   directory.
2. Drop the permissive `_permissive_retrieve` for that subtree (let the
   registry resolve to the vendored file).
3. Run `make test`; expect existing test fixtures to surface real
   sub-schema violations; fix the fixtures, not the validator.

The schemas/README.md captures the refresh protocol so this remains
durable across contributors.

## Why a separate ADR (not just an inline comment)

This is a **principle** about the mock's relationship to real F5, not a
recipe for one specific bug. Future contributors who add a new endpoint
that accepts a declarative payload (e.g. TS, FAST, or future ATC extensions)
should land on this ADR via grep or directory crawl and apply the same
pattern by default. An inline comment in `extensions.py` would document the
DO/AS3 specific call sites; the principle would not survive a refactor
that moves those handlers. The ADR is the durable contract.

## Why this is bigger than ADR 005

ADR 005 documents a workaround for an upstream bug in
`terraform-provider-bigip v1.26.0` (the nil-pointer panic on cancellation).
That workaround is temporary debt with a clear removal trigger when the
upstream fix ships.

ADR 006 is not about a single upstream bug. It is a structural decision
about the mock's contract: **the mock's job is not just to round-trip
bytes, it is to enforce the same input contract real F5 enforces.** That
shifts the mock's role from "convenience" to "executable specification of
what real F5 accepts." Even after every upstream bug is fixed, ADR 006
remains the design principle.

## Cost

- **New mock dependency: `jsonschema>=4.20.0`.** Adds ~5 transitive packages
  (`attrs`, `referencing`, `rpds-py`, `jsonschema-specifications`). Well-
  maintained, widely used, no install footprint concerns.
- **Vendored schema files: ~26 KB total today** (DO 11.6 KB + AS3 14.3 KB).
  Will grow as we vendor referenced sub-schemas, but stays under 100 KB
  even with the full tree vendored.
- **`make test` overhead:** ~5 ms per validation call (jsonschema's
  Draft 7 validator is fast; schemas are cached via `lru_cache`). Negligible.
- **Refresh cadence:** schemas pin to the same version installed on the
  integration VE. A version bump in the runtime-init declaration pairs with
  a schema refresh here.

## Tradeoffs accepted

- **Vendored schemas can drift from upstream.** If F5 ships a 1.47.1 patch
  that tightens a constraint we miss, our pinned schema won't reflect it.
  Mitigated by: explicit version pinning surfaces drift on refresh, and the
  integration round-trip remains the ultimate gate against real F5.
- **Permissive-resolver scope.** Unresolved `$ref`s pass freely today. A
  bug at an inner level — e.g. a VLAN tag out of range, an AS3 monitor
  field misnamed — would still pass the mock and fail in production. The
  acceptable response is to extend vendored coverage as needed, not to
  push deep validation into the first cut.
- **Test-fixture maintenance.** Adding a new test that posts a declaration
  now means the declaration must validate. Slightly higher friction than
  the old "mock accepts anything" world, but the friction surfaces exactly
  the kind of bug PR 3 chased through three cloud iterations.

## Verification

The self-test below confirms both layers (the module-level schema-shape
test in `test_declaration_schemas.py` and the mock-side schema validator)
catch the regression:

1. Temporarily revert `terraform/modules/do-declaration/templates/do.json.tftpl`
   to the `class: "DO"` wrapper shape.
2. `make test-unit` — expect `test_do_declaration_is_direct_device_class`
   to fail (module-level catch).
3. `make test` — expect the mock's POST validation to also fail any test
   that posts the broken fixture (mock-level catch).
4. Reapply the direct-Device shape; both layers green.

The intent of the self-test isn't to verify on every CI run — it's to
verify *once*, at commit time, that the gate works. Running it
periodically (e.g. each Phase 5 refresh) re-confirms continued coverage.

## Implementation pointers

- `mock-f5/app/schemas.py` — validators + permissive resolver
- `mock-f5/schemas/` — vendored schemas + README with provenance
- `mock-f5/app/routers/extensions.py` — DO POST and AS3 POST validation
  calls
- `mock-f5/tests/test_declaration_schemas.py` — module-level fixture
  shape assertions
- `mock-f5/tests/test_do.py` — mock-side fixtures (MIN_DECL, bad_decl,
  good_decl) using the correct direct-Device shape
- `mock-f5/pyproject.toml` — `jsonschema>=4.20.0` dependency

## Related decisions

- **ADR 005** (AS3 apply-race workaround): the immediate cause of PR 3
  iter-7. ADR 005 fixed the upstream defect class; ADR 006 fixes the
  structural class that allowed the original bug to land.
- **CLAUDE.md** ("Everything testable without a real BIG-IP"): ADR 006 is
  the operational definition of "testable" — the mock must enforce the
  same contract real F5 enforces.
