# ADR 007 — Brownfield config discovery: scope, prior art, design

- Date: 2026-05-12
- Status: Accepted

## Context

NexusF5's design principle 3 (`CLAUDE.md`) names declarative config as the
source of truth: every upgrade ends with a Terraform-driven DO/AS3
re-apply and a drift gate. Phases 1-4 built that contract for
**greenfield** declarations — declarations authored in HCL, rendered via
`templatefile()`, applied via `bigip_do` and `bigip_as3` resources, and
validated against vendored vendor schemas (ADR 006).

The unaddressed half of the contract is **brownfield**: an existing
fleet where config lives only on the devices, accumulated over years of
tmsh edits, hand-rolled iRules, and one-off profile tweaks. Lifting that
fleet into declarative source-of-truth is the actual problem an F5
estate owner pays to solve. Until config is extractable, importable,
and round-trippable, the drift gate has nothing to compare against;
NexusF5's "every upgrade re-applies declarations" guarantee is only as
strong as the declarations are honest.

Phase 5's centerpiece is a tool that closes that half of the loop:
walk a real BIG-IP via iControl REST, emit AS3 + DO declarations, and
generate Terraform `import` blocks that point those declarations at
existing `F5Networks/bigip` provider resources.

Before writing the tool, this ADR scopes what F5 and the community
already ship, names the genuine gap, and pins the architectural
decisions that the implementation will follow.

## Prior art summary

The full scoping pass is captured in the Phase 5 kickoff thread; the
load-bearing findings are summarized here so this ADR stands alone.

Every claim below is verified against a primary source — F5 official docs, GitHub repo metadata, or release pages. Quotes are reproduced verbatim where the contract turns on a specific phrase.

| Area | What ships | Brownfield-usable? | Evidence |
|---|---|---|---|
| `GET /mgmt/shared/appsvcs/declare` | Returns the AS3 declaration AS3 itself previously POSTed | **No.** Returns nothing on a device that has never seen AS3. | "All other request methods (GET and DELETE) work with declarations previously supplied via POST and retained by AS3." — [AS3 API Reference, "API Overview"](https://clouddocs.f5.com/products/extensions/f5-appsvcs-extension/latest/refguide/as3-api.html) |
| `GET /mgmt/shared/declarative-onboarding/inspect` | Returns a DO declaration matching the device's current live configuration. Scope: system settings — NTP, DNS, syslog, provisioning, VLANs, self IPs, HA. | **Yes.** The one upstream-shipped brownfield-extraction primitive. | "In BIG-IP DO version 1.7.0 and later, you can use a GET request to the /inspect endpoint to retrieve the current BIG-IP configuration." — [DO HTTP Methods](https://clouddocs.f5.com/products/extensions/f5-declarative-onboarding/latest/http-methods.html). Brownfield usability is the natural reading of "current configuration" (vs. the sibling `GET /mgmt/shared/declarative-onboarding` endpoint, which mirrors AS3's POST-cache behavior). Confirmation against a real never-seen-DO device is part of the optional cloud round-trip in §"Scope of the first cut." |
| F5 Journeys | TMOS→TMOS / TMOS→rSeries config migration | **No.** Not a declarative-extraction tool. | Repo `f5devcentral/f5-journeys` is archived: `isArchived: true, archivedAt: 2026-04-30T20:12:25Z` ([GitHub repo](https://github.com/f5devcentral/f5-journeys); confirmed via `gh repo view --json isArchived,archivedAt`). |
| BIG-IQ config export | Proxies AS3 GET against managed devices | **No.** Same brownfield-blind behavior as AS3 GET, plus a paid-product barrier. | [BIG-IQ AS3 declare API reference](https://clouddocs.f5.com/products/big-iq/mgmt-api/v0.0/ApiReferences/bigiq_public_api_ref/r_as3_declare.html) |
| `f5-automation-config-converter` (ACC) | Offline UCS / SCF / `.conf` → AS3 (or DO) JSON | **Partial.** Closest prior art. Offline-only (no live iControl REST input). No Terraform output. Community-supported. | Last release `v1.24.0` on `2022-10-03` (verified via `gh release list -R f5devcentral/f5-automation-config-converter`). Three years stale. [Repo](https://github.com/f5devcentral/f5-automation-config-converter) · [Releases](https://github.com/f5devcentral/f5-automation-config-converter/releases). |
| Official F5 Python SDKs | `f5-common-python` (deprecated 2019), `f5-icontrol-rest-python` (thin transport) | **No extraction logic.** Useful only as transport. | [`F5Networks/f5-common-python`](https://github.com/F5Networks/f5-common-python) — README states "no longer under active development." |
| `F5Networks/bigip` Terraform provider import | `bigip_as3` imports by partition-name CSV; `bigip_do` imports by **DO task UUID** | **Partial.** AS3 import is brownfield-friendly. DO import is shaped for state-recovery, not brownfield adoption. | bigip_do docs, line 51-55 verbatim: `Importing Existing DO declaration onto terraform can be done by using \`task id\` as \`id\`. ... terraform import bigip_do.do-example2 2543dc37-bd1a-45c1-983f-1155a81489b2` — [provider source](https://github.com/F5Networks/terraform-provider-bigip/blob/master/docs/resources/bigip_do.md). bigip_as3 import ID is partition-CSV — [bigip_as3 docs](https://github.com/F5Networks/terraform-provider-bigip/blob/master/docs/resources/bigip_as3.md). |

## The genuine gap

Three concrete gaps, in order of weight:

1. **Live-device LTM → AS3 extraction.** No F5-shipped or actively-maintained community tool does this. ACC is the closest prior art and it is offline-only and stale. Everything else returns either "what AS3 already deployed" or nothing.

2. **`bigip_do` Terraform import has no clean brownfield path.** The provider expects a task UUID, which on a never-managed-by-DO device does not exist. The path forward is either (a) first-apply-then-import (POST a DO declaration via the provider, capture the task ID, then `import` that ID back) or (b) document that DO declarations land via initial apply, not import. Either way this is an architectural decision the tool needs to make explicit, because it is not the default-shaped Terraform import flow.

3. **End-to-end: live device → declarations + Terraform import blocks.** Even if the extraction side were already shipped, no tool emits the `import { to = bigip_as3.example, id = "Tenant_A,Tenant_B" }` blocks that turn extracted declarations into adoptable Terraform state. The Terraform-import-block layer is genuinely missing across the upstream landscape.

## Decision

Build a Python CLI under `tools/brownfield/` that:

1. **Consumes `/mgmt/shared/declarative-onboarding/inspect`** for system DO. Do not reinvent system extraction — call upstream and accept the response. Vendored ADR-006 schemas validate the output before it is written.

2. **Walks LTM iControl REST endpoints** (virtuals, pools, monitors, SSL profiles, persistence, iRules) and serializes the discovered objects into a valid AS3 declaration. This is the bulk of the work and the genuine contribution.

3. **Emits Terraform `import` blocks** pointing at `bigip_do` and `bigip_as3` resources. AS3 import IDs are partition-name CSV. `bigip_do` follows the **apply-no-op adoption** flow defined below (because the provider has no brownfield-shaped DO import).

4. **Validates emitted declarations against the vendored DO/AS3 schemas** from `mock-f5/schemas/` (ADR 006). The same schemas the mock enforces become the contract for the extractor's output. A declaration the tool emits is a declaration the mock — and by extension real F5 — accepts.

5. **Runs end-to-end against the mock-f5 stack.** The 50-device Phase 3 mock topology is the development target. One optional cloud round-trip against a real BIG-IP VE validates the iControl REST shape assumptions; if it fails to round-trip the same payload, the gap is documented and the mock is upgraded toward fidelity (ADR 006's principle, applied to extraction).

## Decision framework

### What the tool does

- **System layer (DO):** Call `GET /mgmt/shared/declarative-onboarding/inspect`. Validate the response against the vendored DO schema. Write `<device>.do.json`.
- **Application layer (AS3):** Walk LTM:
  - `GET /mgmt/tm/ltm/virtual` → AS3 `Service_HTTP` / `Service_HTTPS` / `Service_TCP` / `Service_UDP` mapping
  - `GET /mgmt/tm/ltm/pool` → AS3 `Pool` (members, monitor refs)
  - `GET /mgmt/tm/ltm/monitor/*` → AS3 `Monitor_*` (HTTP, HTTPS, TCP, ICMP, custom)
  - `GET /mgmt/tm/ltm/profile/*` → AS3 profile classes (HTTP, ClientSSL, ServerSSL, OneConnect)
  - `GET /mgmt/tm/ltm/persistence/*` → AS3 `Persist` (cookie, source-addr, dest-addr)
  - `GET /mgmt/tm/ltm/rule` → AS3 `iRule` (TCL body verbatim; documented as "ported as-is, hand-review required")
  - Group by partition into AS3 tenants. Validate against vendored AS3 schema. Write `<device>.as3.json`.
- **Terraform layer:** For each emitted declaration, generate an `import.tf` containing `import { to = ..., id = "..." }` blocks plus a `moved` block for any prior `terraform state mv` migrations. AS3 import IDs are derived from tenant names discovered during the walk. DO import follows §3 below.

### Out of scope (explicit)

Out-of-scope items are as load-bearing as in-scope items. Each of these is a "do not do this in Phase 5" line that the first-cut PR is bound by:

- **No multi-device fleet extraction in the first PR.** First cut is single-device end-to-end. Multi-device walk (parallelize across an inventory, aggregate per-device declarations, generate fleet-shaped Terraform layout) is the second PR, after the single-device contract is proven.
- **No fleet-scale concurrency.** The tool is single-process, single-threaded against one device at a time. No worker pool, no async fanout, no batched iControl REST. Fleet scaling is a separate concern after the first cut works correctly.
- **No real AWS VE round-trip during development.** All development is local against the mock-f5 stack. **One** optional cloud round-trip at the end of Phase 5 validates iControl REST shape assumptions, bounded by `tools/integration_wrapper.py` (45-minute timeout, $5-10 budget, two-iteration max per Phase 5 discipline). If the round-trip fails twice, stop-and-discuss before the third.
- **No ASM/APM extraction.** Out of scope per `CLAUDE.md` "Where not to go." Tool walks LTM and system DO only. Workloads with ASM/APM features still need manual post-extraction work; the tool does not pretend otherwise.
- **No iRule semantic translation.** TCL rules are extracted verbatim and emitted as AS3 `iRule` declarations. Operators hand-review whether the rule is still appropriate at the target version; the tool does not opine.
- **No drift reconciliation against an existing Terraform state.** First-pass brownfield adoption only. A future tool can do "extracted declaration vs current declaration → diff" but that is out of scope here.
- **No real-time monitoring or continuous reconciliation.** One-shot extraction. Re-running the tool produces fresh declarations; intended for adoption events, not steady-state drift detection (which is already covered by the ADR-006 schema + `terraform plan -detailed-exitcode` gate).
- **No multi-tenant decomposition heuristics in the first PR.** Each F5 partition maps 1:1 to one AS3 tenant. Multi-tenant patterns — tenant-per-application, tenant-per-environment, sharing — are deferred to a later PR once single-tenant adoption is proven in practice.

### Why we do not contribute upstream to ACC instead

Considered. Rejected for the first cut. ACC's offline / UCS-only architecture is the wrong shape for our use case: NexusF5's whole stance is "declarative source of truth from live state," and ACC is "declarative source of truth from a UCS snapshot." Adding live-iControl-REST input to ACC would be a substantive architectural change to a Node.js codebase that has not seen a release in three years. The contribution we want to make is shaped differently — live-device first, Python (matching NexusF5's mock-f5 / observability stack), schema-validated against the same vendored schemas that gate ADR 006 — and lives natively in the project that consumes it.

A reasonable future state: if the Python tool proves out the live-device extraction shape, a follow-up PR upstream into ACC adding a `--from-icontrol-rest` flag, sharing the extraction logic via a portable mapping table. That is a follow-on, not a Phase 5 deliverable.

### Why we do not require BIG-IQ

BIG-IQ's AS3 export proxies through to the AS3 GET endpoint, which has the same brownfield-blind behavior. Standing up BIG-IQ to extract config from devices that have never seen AS3 would not solve the problem. Independently, BIG-IQ is a paid product with non-trivial install — gating a portfolio-grade extractor on it would make the tool unusable by anyone evaluating the project.

## Scope of the first cut

The first PR ships a tool that extracts and round-trips a **single device** end-to-end against the mock-f5 stack, with one AS3 tenant containing a mix of LTM object types:

- 1+ virtual server (HTTP and HTTPS)
- 1+ pool with monitor refs and 3+ members
- 1+ custom HTTP monitor with non-default send/recv strings
- 1+ ClientSSL profile (cert chain reference resolved or stubbed)
- 1+ cookie persistence profile
- 1+ iRule

The emitted declarations pass:
- Vendored AS3/DO schema validation (ADR 006 gate)
- `terraform plan -detailed-exitcode == 0` after the generated `import` blocks are applied
- Re-extraction round-trip (extract → apply via `bigip_as3` → re-extract → byte-stable up to documented normalization)

Multi-device fleet extraction is the second PR; the first PR proves the contract on one device.

### `bigip_do` import — the apply-no-op adoption flow

The `F5Networks/bigip` provider's `bigip_do` import requires a task UUID from a prior DO POST. On a brownfield device, no such UUID exists, and the provider has no alternative import shape. The chosen workaround is named **apply-no-op adoption** so future PR comments and code references can name it in one phrase:

1. The tool extracts the DO declaration via `/inspect`.
2. The tool writes the declaration JSON but **does not emit a `bigip_do` import block**. Instead it emits a `bigip_do` resource block with the extracted declaration as the `do_json` value.
3. First `terraform apply` POSTs the declaration to the device. Because the declaration is structurally identical to what the device already runs, the apply is a **no-op at the F5 layer** (DO sees no diff) but generates a task UUID that the provider stores in state.
4. From that point forward, the resource is fully managed by Terraform with a real task ID. Subsequent applies behave normally.

The pattern is named "apply-no-op adoption" — short enough to reference in code comments (`# apply-no-op adoption: see ADR 007`) and PR descriptions without re-explaining. The tool's emitted README documents it explicitly rather than papering over it. An upstream issue against `F5Networks/terraform-provider-bigip` requesting a brownfield-friendly DO import path is the natural follow-up.

`bigip_as3` import works the documented way: the tool discovers tenant names from the live device, emits `import { to = bigip_as3.<name>, id = "TenantA,TenantB" }`, and `terraform plan` accepts it. No special pattern needed there.

## Consequences

- **The extractor is a contract producer for ADR 006's validators.** Declarations the tool emits must pass the same vendored-schema gates the mock and module-level tests enforce. The two ADRs compose: 006 defines what valid means, 007 produces output that meets the definition.
- **Mock fidelity demand grows.** The mock currently returns minimal `/mgmt/tm/ltm/*` responses (Phase 3 scope). The extractor exercises those endpoints in shapes the mock has not been asked to produce. Each shape the extractor needs becomes a mock fidelity issue tracked alongside the tool's development.
- **DO `/inspect` becomes a hard dependency.** The mock must implement `/inspect` faithfully — schema-valid output reflecting the mock's in-memory device state. New mock-f5 work.
- **Real-VE round-trip is optional for Phase 5.** The tool develops against the mock. One real BIG-IP VE round-trip at the end of Phase 5 validates the iControl REST assumptions; the integration wrapper (`tools/integration_wrapper.py`, 45-minute timeout, $5-10 budget) bounds the cost. Two-iteration max before stop-and-discuss per Phase 5 discipline.
- **iRule extraction is verbatim and lossy in spirit.** A TCL rule extracted at TMOS 16.1 and applied to TMOS 17.1 may rely on deprecated commands. The tool says so in its output ("X iRules extracted; hand-review against TMOS 17.1 deprecation notes recommended"); it does not attempt static analysis.

## Tradeoffs accepted

What this decision costs, what it doesn't address, what it assumes:

- **ASM/APM-managed workloads need additional manual work post-extraction.** The tool extracts LTM + system DO only. Estates with ASM (web application firewall) or APM (access policy management) features will land partially-declarative: their LTM layer is captured by this tool, their ASM/APM layer remains imperative. This is an honest gap, not a hidden one — the tool's emitted README names it on the cover page, and post-extraction operators get a clear "ASM policies detected on N virtuals; not extracted; manual port required" message rather than a silent omission.
- **Apply-no-op adoption requires operator confidence in the extracted declaration before first apply.** The flow assumes the extracted declaration is structurally identical to live device state; if extraction is buggy, the "no-op apply" is actually a *destructive apply* that overwrites real config with the buggy extraction. Mitigations: (1) the ADR-006 schema validators gate the declaration's structural correctness before anything reaches Terraform; (2) the first PR ships with a `--dry-run` mode that prints the would-be POST without applying; (3) the documented operator workflow is "extract → schema-validate → dry-run → human review → first apply" — never extract-and-apply in a single command. The tool surfaces this in its CLI help, not just the README.
- **Single-tenant initial scope; multi-tenant decomposition deferred.** The first PR maps F5 partitions 1:1 to AS3 tenants and stops there. Real estates often want finer decomposition (tenant-per-application, tenant-per-team), but inferring those boundaries from device state is impossible without operator intent. The tool emits the mechanical 1:1 mapping; operators refactor the emitted declaration to the tenant shape they want. A future PR may take a `--tenant-map` config file as input, but it is not first-cut.
- **Partition-level granularity for AS3 tenants.** Corollary of the previous: tools that walk LTM cannot infer "application boundaries" that a human author would express. The tool does not guess; it surfaces the partition shape exactly as F5 represents it.
- **Profile reference resolution is best-effort.** Some profiles reference certs, keys, or auth objects that live in `/Common`. The tool emits references as-is; if `/Common/clientssl_default` is referenced and exists on the target, the declaration applies cleanly. If the target lacks it, the apply fails — same as it would on real F5.
- **No anonymization in the extractor.** Extracted declarations contain real IPs, hostnames, and pool member addresses. Operators running this against a production fleet are responsible for handling the output. The tool's README is explicit about this. Anonymization is a separate concern; out of scope.
- **Idempotency boundary.** The tool is read-only against the source device. The Terraform-import-block layer's first apply is the only mutation, and it is by design (the apply-no-op adoption flow above).

## Testing strategy

The ADR-006 vendored schemas are the contract this tool produces against, and they double as a cheap hermetic test surface. The full test pyramid:

1. **Hermetic schema round-trip (the cheapest, fastest test).** Extract from a mock-f5 device → emit AS3/DO declaration → run the emitted declaration through `mock-f5/app/schemas.py::validate_{do,as3}_declaration` (the same validators the mock POST handlers enforce). Assert pass. This catches the entire class of "tool emits invalid declarations" bugs without spinning up Terraform, AWS, or a real BIG-IP. **A declaration the tool emits that fails ADR-006 validation is by definition a tool bug.** Lives under `tools/brownfield/tests/test_schema_roundtrip.py`.

2. **Mock-stack apply round-trip.** Extract from mock → emit declaration + Terraform import block → `terraform apply` against the mock → `terraform plan -detailed-exitcode` returns 0 (zero drift). This exercises the full pipeline including the apply-no-op adoption flow against a real Terraform run, without cloud spend. Lives under `tools/brownfield/tests/test_mock_apply.py` and runs in CI.

3. **Re-extraction byte-stability.** Extract → apply via Terraform → re-extract → assert the second extraction matches the first up to documented normalization (field ordering, default-value omission, comment stripping). Catches non-deterministic emission. Lives in the same mock-apply test file.

4. **Optional cloud round-trip (one).** Against a real AWS BIG-IP VE pair tagged for the brownfield extractor work, the same end-to-end pipeline runs once at the end of Phase 5. Bounded by `tools/integration_wrapper.py` (45-minute timeout, two-iteration ceiling, $5-10 budget). If the cloud round-trip fails in shapes the mock did not reproduce, those become mock-fidelity issues per ADR 006's principle — the mock catches up to real F5, not the other way around.

Test (1) is the workhorse: it runs in milliseconds, requires no network, and forecloses on the largest class of extractor bugs by construction. The schemas the mock and the tool both validate against are the executable specification of "what real F5 accepts," and ADR 006 already pins them. ADR 007's tool produces against that spec.

## Alternatives considered

- **Use ACC and stop.** Rejected. Offline-only, stale, no Terraform output. Solves a different problem (UCS-to-declarative) than ours (live-fleet-to-declarative).
- **Contribute ACC's `--from-icontrol-rest`.** Plausible follow-on, not a first cut. See "Why we do not contribute upstream to ACC instead" above.
- **Use BIG-IQ.** Rejected. Doesn't extract from brownfield; paid product; install footprint.
- **Use `GET /mgmt/shared/appsvcs/declare` and accept the brownfield gap.** Rejected. That endpoint is empty on the fleet shape we are targeting; using it would solve the easy case (AS3-managed devices) and ignore the actual problem.
- **Ship Terraform import blocks only, no extraction.** Rejected. Import blocks need the declaration content to point at. Without extraction, the user has nothing to import.

## Related

- `CLAUDE.md` design principle 3 — declarative config is source of truth. This ADR closes the brownfield half of that principle.
- `docs/decisions/002-terraform-scope.md` — Terraform owns DO/AS3 declarations. The extractor's output lands in Terraform.
- `docs/decisions/006-mock-contract-fidelity.md` — vendored schemas validate inputs. The extractor's output is validated against the same schemas; ADR 006's principle composes with this one.
- `mock-f5/schemas/` — DO 1.47.0 and AS3 3.51.0 schemas. The extractor targets these versions.
- `tools/brownfield/` — implementation lives here (to be created in the Phase 5 PR following this ADR's review).
- Upstream: [DO `/inspect` docs](https://clouddocs.f5.com/products/extensions/f5-declarative-onboarding/latest/http-methods.html), [AS3 API reference](https://clouddocs.f5.com/products/extensions/f5-appsvcs-extension/latest/refguide/as3-api.html), [`F5Networks/bigip` provider](https://registry.terraform.io/providers/F5Networks/bigip/latest/docs), [`f5-automation-config-converter`](https://github.com/f5devcentral/f5-automation-config-converter).
