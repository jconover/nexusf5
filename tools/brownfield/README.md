# brownfield — F5 BIG-IP config-discovery CLI

Walk a live F5 BIG-IP via iControl REST and emit AS3 + DO declarations
plus Terraform import blocks for adopting existing fleet config into
declarative source of truth. Per [ADR 007](../../docs/decisions/007-brownfield-config-discovery.md).

The problem this tool solves: existing F5 estates have years of
accumulated config that lives only on the devices — tmsh edits, hand-
rolled iRules, profile tweaks never declared in IaC. Drift detection
has nothing to compare against until config is extracted, importable,
and round-trippable. NexusF5's "every upgrade re-applies declarations"
guarantee is only as strong as the declarations are honest. This tool
makes the declarations honest.

## Quickstart

Single-device extraction against the local mock-f5 stack:

```sh
cd tools/brownfield
uv sync

# 1. Extract → write 5 files into ./extracted/bigip-lab-01/
uv run python -m brownfield extract \
    --base-url http://localhost:8100/bigip-lab-01 \
    --hostname bigip-lab-01 \
    --output ./extracted/bigip-lab-01

# 2. Schema-validate the emitted declarations (ADR 006 gate)
uv run python -m brownfield validate ./extracted/bigip-lab-01

# 3. Run terraform plan to review the import
cd ./extracted/bigip-lab-01
terraform init
terraform plan        # expect: import only, no create/update/delete

# 4. HUMAN REVIEW of as3.json and do.json against operator intent

# 5. Apply
terraform apply
```

Real F5 (HTTP Basic auth, self-signed cert):

```sh
uv run python -m brownfield extract \
    --base-url https://bigip-dc1-042.example.net \
    --hostname bigip-dc1-042 \
    --auth admin:$BIGIP_PASSWORD \
    --no-verify-tls \
    --output ./extracted/bigip-dc1-042
```

Dry-run (preview without writing files):

```sh
uv run python -m brownfield extract \
    --base-url http://localhost:8100/bigip-lab-01 \
    --hostname bigip-lab-01 \
    --output ./extracted/bigip-lab-01 \
    --dry-run
```

The CLI deliberately separates `extract` and `validate` into distinct
invocations. There is no `--auto-apply` flag or combined command. The
operator workflow above is the documented contract per [ADR 007
§Tradeoffs](../../docs/decisions/007-brownfield-config-discovery.md).

## What the tool emits

Per extraction, five files in the output directory:

| File | Content |
|------|---------|
| `as3.json` | AS3 envelope declaration applying to the F5 partition |
| `do.json` | DO declaration matching live system state (from `/inspect`) |
| `main.tf` | `bigip_as3` + `bigip_do` resource blocks |
| `imports.tf` | Terraform import block for `bigip_as3` (AS3 only) |
| `README.md` | Per-extraction adoption summary (auto-generated, deterministic) |

## What adoption means for the extracted partition

When you `terraform apply` the extracted declaration, AS3 takes
**ownership** of the adopted partition (typically `/Common`).
Subsequent GUI or `tmsh` edits to objects in that partition will
surface as drift on the next `terraform plan`.

The adoption boundary is concrete:

- **Inside the boundary:** every object this tool walked and emitted
  into the declaration. The per-extraction README lists each one by
  name.
- **Outside the boundary:** ASM/APM policies (not extracted per
  [ADR 007 §Out of scope](../../docs/decisions/007-brownfield-config-discovery.md));
  any `/Common` objects the extractor filtered as F5 built-ins; any
  objects added to the partition after the extraction was run.

If you need to add new objects to the adopted partition, the
supported path is: edit the AS3 declaration, re-apply via Terraform.
The drift gate catches out-of-band edits.

### Why AS3 tenant name equals partition name

AS3 3.51.0 has no logical-vs-physical tenant separation — see
[ADR 007 Addendum 2026-05-13](../../docs/decisions/007-brownfield-config-discovery.md#addendum-2026-05-13-as3-tenant-naming-constraint).
Multi-device disambiguation lives at the Terraform resource-name layer
(`bigip_as3.bigip_lab_01_Common` vs `bigip_as3.bigip_lab_02_Common`),
not at the tenant name. Two devices extracting `/Common` into the same
Terraform workspace produce two resources with different identifiers,
each containing an AS3 tenant named `Common` scoped to its provider.

## Scope (first-cut PR)

In scope per [ADR 007 §Scope of the first cut](../../docs/decisions/007-brownfield-config-discovery.md):

- LTM objects: virtual servers, pools (with members), HTTP monitors,
  ClientSSL profiles, cookie persistence, iRules
- System DO via `/mgmt/shared/declarative-onboarding/inspect`
- Single device, single partition per invocation
- Mock-stack development; one optional real-VE cloud round-trip at
  end of Phase 5

Out of scope:

- ASM/APM extraction (manual port required for affected workloads)
- TCP/HTTPS/ICMP monitor types (HTTP only)
- ServerSSL, OneConnect, HTTP profiles (ClientSSL only)
- Source-addr / dest-addr persistence (cookie only)
- LTM Node objects (pool members carry node info inline)
- Multi-device fleet extraction (deferred to PR 2)
- Fleet-scale concurrency (single-threaded by design)
- iRule semantic translation (verbatim TCL pass-through)
- Multi-tenant decomposition heuristics (1:1 partition→tenant)

## Re-extraction byte-stability

[ADR 007 §Scope of the first cut](../../docs/decisions/007-brownfield-config-discovery.md)
requires re-extraction byte-stability "up to documented normalization."
The brownfield tool's normalizations:

| Normalization | Source |
|---|---|
| Built-in object filtering | Vendored ACC v1.24.0 list — `brownfield/builtins.py` |
| Partition → AS3 tenant 1:1, literal name | ADR 007 Addendum 2026-05-13 |
| Hostname → TF identifier (hyphen→underscore) | ADR 007 Addendum 2026-05-13 |
| AS3 schemaVersion pin (3.50.0) | Matches project's existing as3-declaration template |
| DO schemaVersion pin (1.40.0) | Matches mock-f5 `do_info` reported version |
| README list sorting | `brownfield/emit/readme.py` — alphabetical within categories |
| JSON serialization: `sort_keys=True, indent=2` | `brownfield/cli.py::_dumps` |

The `test_gate_3_re_extraction_byte_stable_*` tests enforce that
re-running `extract` against unchanged device state produces identical
bytes across as3.json, do.json, main.tf, imports.tf, README.md.

## Testing strategy

Per [ADR 007 §Testing strategy](../../docs/decisions/007-brownfield-config-discovery.md),
three gates compose:

1. **Hermetic schema round-trip** — emitted declarations validate
   against the vendored ADR 006 schemas (`tests/test_three_gate.py`).
2. **Mock-stack apply round-trip** — emitted AS3+DO POST to the
   mock-f5 ASGI app and are accepted (root-level schema gate, same
   path real F5 uses).
3. **Re-extraction byte-stability** — extract → emit → POST → re-walk
   → re-emit → byte-stable.

`uv run pytest` runs all three layers hermetically in milliseconds.

## File layout

```
brownfield/
├── builtins.py          # vendored F5 built-in object list, ACC v1.24.0
├── cli.py               # argparse subcommands: extract, validate
├── client.py            # IControlRestClient (httpx wrapper)
├── walker.py            # iControl REST walker → WalkerOutput
├── __main__.py          # python -m brownfield entry point
└── emit/
    ├── as3.py           # WalkerOutput → AS3 envelope declaration
    ├── do.py            # walker /inspect → DO declaration passthrough
    ├── terraform.py     # main.tf + imports.tf rendering
    ├── readme.py        # per-extraction README generator (deterministic)
    └── _shape.py        # parse_destination, hostname normalization
```

## Related

- [ADR 007 — Brownfield config discovery: scope, prior art, design](../../docs/decisions/007-brownfield-config-discovery.md)
- [ADR 006 — Mock contract fidelity (vendored schemas)](../../docs/decisions/006-mock-contract-fidelity.md)
- [ADR 002 — Terraform owns declarations, not upgrade flow](../../docs/decisions/002-terraform-scope.md)
- Upstream:
  [`f5devcentral/f5-automation-config-converter`](https://github.com/f5devcentral/f5-automation-config-converter) (built-in list provenance @ v1.24.0),
  [DO `/inspect` docs](https://clouddocs.f5.com/products/extensions/f5-declarative-onboarding/latest/http-methods.html),
  [AS3 API reference](https://clouddocs.f5.com/products/extensions/f5-appsvcs-extension/latest/refguide/as3-api.html),
  [`F5Networks/bigip` provider](https://registry.terraform.io/providers/F5Networks/bigip/latest/docs)
