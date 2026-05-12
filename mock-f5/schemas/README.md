# Vendored F5 ATC schemas — mock contract fidelity

This directory holds **pinned, version-stamped copies of F5's published JSON
schemas** for the Automation Tool Chain extensions the mock impersonates
(Declarative Onboarding and AS3). The mock's POST endpoints validate request
bodies against these schemas before accepting them, so a declaration that
would be rejected by a real BIG-IP is rejected by the mock at `make test`
time. See `docs/decisions/006-mock-contract-fidelity.md` for the principle
and rationale.

## Why these are vendored, not fetched at runtime

- **Reproducibility.** A test that depends on network availability is a flaky
  test. CI must run offline.
- **Version pinning.** The pinned schema version matches the extension
  version installed on the integration VE (DO 1.47.0 + AS3 3.51.0; see
  `terraform/modules/ve-instance/runtime-init-userdata.sh.tftpl`). Upgrading
  the extension on the VE pairs with a refresh of these schemas.
- **Provenance.** Each schema file is sourced directly from F5's release tag
  and matches what the corresponding RPM ships with on a real BIG-IP.

## What's here

```
schemas/
├── do/
│   └── v1.47.0/
│       └── base.schema.json    # F5 DO root — class:"Device" const, properties allowlist
└── as3/
    └── v3.51.0/
        └── as3-request-schema.json   # F5 AS3 root — oneOf [ADC | AS3 wrapper | patch]
```

## Provenance

| File | Upstream tag | Upstream URL |
|------|--------------|--------------|
| `do/v1.47.0/base.schema.json` | F5Networks/f5-declarative-onboarding tag `v1.47.0` | https://github.com/F5Networks/f5-declarative-onboarding/blob/v1.47.0/src/schema/latest/base.schema.json |
| `as3/v3.51.0/as3-request-schema.json` | F5Networks/f5-appsvcs-extension tag `v3.51.0` | https://github.com/F5Networks/f5-appsvcs-extension/blob/v3.51.0/src/schema/latest/as3-request-schema.json |

## Scope of validation

The mock's validator runs each schema against the **root** of the request
body. Both schemas use a `class` discriminator and `additionalProperties:
false` at the root, which is what catches the bug 7 class of error (wrong
outer wrapper, e.g. `class: "DO"` when F5 DO requires `class: "Device"`).

The schemas internally `$ref` other sub-schemas (`system.schema.json`,
`network.schema.json`, AS3 `core-schema.json`, etc.) which are **not** yet
vendored. Mock validation treats unresolved `$ref` as a permissive
empty-schema (pass-through). This means inner-class validation (DNS server
format, VLAN spec, AS3 Service_HTTP shape, etc.) is **not** enforced at the
mock layer today.

This is a deliberate first-cut scope: the bug that took down PR 3 was a
root-level shape error, and root-level validation closes that class of error
without expanding the vendored schema tree. When the next bug surfaces at an
inner level, vendor the referenced sub-schemas + bump validator strictness
in one focused PR. ADR 006 documents this incremental approach.

## How to refresh

1. Identify the version installed on the integration VE (search
   `runtime-init-userdata.sh.tftpl` for `extensionVersion:`).
2. Update the directory name and pinned tag in this README.
3. `curl` the new schema file(s) from the matching upstream tag.
4. Run `make test` — expect failures to surface real schema drift; either
   fix declarations or document the divergence in the ADR.
