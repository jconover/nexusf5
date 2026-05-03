# ADR 003 — Hybrid vs. immutable: which workloads get which track

- Date: 2026-05-03
- Status: Accepted

## Context

NexusF5 ships two upgrade tracks:

- **Hybrid (in-place).** The primary track. Existing HA pair stays put;
  Ansible drives `preflight → backup → image install → boot switch →
  health gate → postcheck` against the live device. Validated against the
  50-device mock-f5 stack in Phase 3 and against an AWS BIG-IP VE pair in
  Phase 4 PR 2.
- **Immutable (provision-and-cutover).** The secondary track. A new VE is
  provisioned at the target version, the same DO/AS3 declarations apply
  to it as to the hybrid path, traffic flips via DNS, the old VE drains
  and is destroyed. Demonstrated in Phase 4 PR 3 against a real AWS VE.

Both tracks reach the same end state (fleet at target version, declarations
applied, no drift). The choice between them is *not* about which track is
"better." It is about which workload's failure modes, change-management
constraints, and config shape suit each track's mechanics. Picking wrong
costs unnecessary risk on one side and unnecessary churn on the other.

This ADR names workload categories on each side of the line so the
decision is concrete, not philosophical.

## Decision

Default to the **hybrid track**. Move a workload to the **immutable
track** only when one of the named criteria below applies.

The bias toward hybrid is deliberate: most existing F5 estates have
years of accumulated config, change processes built around in-place
upgrades, and operators trained on the runbook the hybrid track
implements. Forcing those workloads through cutover is fighting the
shape of the existing operational reality.

## Decision framework

### Hybrid track — default for these categories

1. **Existing HA pairs with years of accumulated config.**
   Multi-year-old devices accumulate config that was never AS3-ified:
   ad-hoc tmsh changes, hand-edited bigip.conf entries, profile tweaks
   that were never declared. Cutting over to a new VE means
   reconstructing all of that. The hybrid track keeps it intact across
   the upgrade — TMOS's two-volume boot design carries the running
   config through the volume swap unchanged.

2. **Custom iRules not yet ported to AS3.**
   AS3 supports declarative iRules via the `iRule` class, but a real
   estate often has decade-old iRules with custom state machines, side
   effects, and tcl-only constructs that don't translate cleanly. Until
   those iRules are ported (or formally retired), hybrid is the only
   safe track — immutable would force a same-day port-or-cutover decision
   under upgrade pressure.

3. **Environments where change management has signed off on in-place
   upgrades for years.**
   Some change-control regimes (PCI-DSS environments, regulated banking
   estates, healthcare clinical-pathway VIPs) have CAB-approved
   procedures for in-place upgrades and *no approval at all* for
   replace-and-cutover. Switching tracks invalidates the approval
   chain, which is months of paperwork. Hybrid keeps the existing
   approval chain valid.

4. **Workloads with TLS session state or sticky-session affinity that
   the application cannot recreate gracefully.**
   The hybrid track's mid-flight failover is a fast TCP RST; clients
   reconnect within seconds. Cutover via DNS shifts the connection to
   a new device that has no session memory of the old client. For
   stateless workloads this is fine; for workloads where the
   application stores state on the load balancer (TLS resumption tickets,
   HTTP session affinity, persistence profiles), hybrid preserves the
   state through the upgrade.

5. **VLAN-tagged or three-NIC topologies where a new VE's network
   attachment is non-trivial.**
   New VE provisioning means new ENIs, new VLAN tags, new self-IPs,
   often new mgmt-vs-data subnet decisions. For workloads with
   non-trivial network topology, the hybrid track sidesteps the
   re-attachment cost entirely — the existing device's network
   attachment is already correct.

### Immutable track — switch tracks for these categories

1. **Greenfield deployments.**
   New environments, new VPCs, new tenants. There's no accumulated
   config to preserve and no existing change-management approval to
   honour. The immutable track's "provision at target version, apply
   declarations, validate, exit" lifecycle is shorter than the hybrid
   track's preflight/backup/install/boot/gate/postcheck flow.
   Greenfield should not use hybrid.

2. **Workloads that tolerate a DNS cutover window.**
   Operations where a 5-30 minute drain window with traffic split
   between old and new is acceptable: B2B APIs with retries, internal
   admin VIPs, batch traffic, session-resumable web apps. ADR 004
   covers the drain-window mechanics. If the workload cannot tolerate
   *any* duplicate-traffic window, hybrid is the safer choice.

3. **AS3-managed config from day one.**
   The whole tenant config lives in an AS3 declaration, no iRules
   outside the declaration, no tmsh-only side effects. The declaration
   is the authoritative description; reconstructing the device from it
   is a no-op of the immutable track's first apply. Phase 4 PR 1's
   declarations are this shape.

4. **Environments where infrastructure-as-code is fully embraced.**
   Terraform owns the declarations, Ansible owns the runbook, all
   changes go through PRs. There's no off-IaC backchannel making
   changes that immutable cutover would erase. If there's a "yeah we
   sometimes ssh in and tmsh-edit" culture, hybrid is the safer track
   until that's resolved.

5. **Same-AMI / same-Marketplace-image refresh scenarios.**
   When the upgrade is "rebuild the VE on the latest patched
   marketplace image" (e.g. quarterly OS-hardening refresh), immutable
   matches the operational shape directly: the old VE is replaced by a
   new VE at the target image, declarations reapplied, done. Hybrid
   would re-image the existing volumes in place, which is more work
   than the situation calls for.

### Edge cases worth naming explicitly

- **AS3-managed but with iRules that don't have AS3 equivalents.**
  Hybrid until the iRules are ported. The fact that 95% of the config
  is declarative does not save the 5% that isn't; cutover would lose
  it. Reassess after the iRule port lands.

- **Greenfield environment but inheriting a legacy migration path.**
  Treat as greenfield → immutable. The fact that the project's
  *predecessor* used hybrid does not bind a new environment to the
  same track. Each environment makes its own choice.

- **Mixed estate where most devices are hybrid-tracked but one tenant
  is greenfield.**
  Run both tracks simultaneously. The wave orchestration is per-device;
  there is no "fleet must be on one track" constraint. Mixed is the
  expected steady state for an organization that builds new
  environments while maintaining old ones.

- **Workload with a planned hardware refresh in 6 months.**
  Hybrid for this upgrade cycle; immutable for the post-refresh
  environment. There's no value in cutting over a workload that will
  be cut over again on a hardware boundary; do it once on the boundary.

## Consequences

- **Track selection is per-workload, not per-fleet.** Each tenant or
  device group gets its own track decision based on the criteria above.
  The fleet-level wave orchestration runs both tracks in parallel —
  hybrid waves and immutable waves are independent.
- **AS3 portability is the load-bearing claim of the immutable track.**
  If the same AS3 declaration applied to a hybrid-upgraded VE differs
  from the one applied to a freshly-provisioned VE, the immutable
  track is broken. Phase 4 PR 3's `make integration-immutable`
  exercises this with the unchanged `do-declaration` and
  `as3-declaration` modules from PR 1.
- **Operators learn one track per workload.** Hybrid workloads use the
  Phase 3 wave orchestration UI and runbooks. Immutable workloads use
  the Phase 4 PR 3 cutover playbook + drain runbook. Newcomers don't
  have to learn both unless they're moving a workload between tracks.
- **Cross-track drift is detectable.** Both tracks end with the same
  drift gate (`terraform plan -detailed-exitcode == 0`). A hybrid
  upgrade and an immutable cutover, against the same declaration, end
  in the same state — that's the testable invariant.

## Alternatives considered

- **One track only (hybrid or immutable).** Rejected. Hybrid-only
  forces greenfield and AS3-clean tenants through machinery they don't
  need. Immutable-only forces existing-estate workloads through
  cutovers that violate their change-management approval and risk
  losing accumulated config.
- **Track selected by environment (lab=immutable, prod=hybrid, or
  vice-versa).** Rejected. The shape that matters is the workload's
  config history and tolerance for cutover, not the environment label.
  Pinning to environment cuts orthogonally to the right axis.
- **Automatic track selection from declaration metadata.** Rejected for
  v1. The decision involves change-management and operational context
  the declaration cannot encode. Codifying the decision tree in the
  ADR (this document) is the lighter-weight path; revisit automation
  after the decision tree has been used in anger across multiple
  workloads.

## Related

- `docs/decisions/002-terraform-scope.md` — Terraform owns DO/AS3,
  Ansible owns the upgrade flow. Both tracks honour this split.
- `docs/decisions/004-cutover-safety.md` — drain windows and rollback
  triggers for the immutable track.
- `terraform/immutable-track/README.md` — the demonstration shape this
  ADR justifies.
- `runbooks/05-running-a-wave.md` — operator procedure for the hybrid
  track. The immutable track's operator procedure lives in the
  cutover playbook itself, since the round-trip is simpler.
