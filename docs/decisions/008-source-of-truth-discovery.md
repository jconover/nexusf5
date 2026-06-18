# ADR 008 — Source of truth for the fleet: static inventory → Nautobot discovery

- Date: 2026-06-18
- Status: Proposed

## Context

NexusF5 drives waves off `ansible/inventory/hosts.yml` — a hand-authored
file listing 50 invented mock devices, partitioned into `canary` /
`wave_1` / `wave_2` / `wave_3` groups. That is correct for the mock-stack
demo and for proving the wave/gate logic, but it encodes a fiction: the
fleet census is a static YAML file an engineer maintains by hand.

A real F5 estate is not static and not hand-countable. Devices are added
and decommissioned. Some run on dedicated hardware; some run as **VE**
(Virtual Edition) VMs on ESXi/vCenter — same TMOS, but they *also* exist
as VMware VMs with their own placement, datastore, and lifecycle. At
arbitrary scale, *something has to discover what is actually out there*
and what state each device is in (TMOS version, HA role, active boot
volume) — and keep that current without an engineer editing YAML.

This is the **inventory / source-of-truth** layer. It is a sibling to
ADR 007 (brownfield *config* discovery): 007 walks a device and extracts
its DO/AS3 *configuration*; this ADR is about discovering the *fleet and
its runtime state* — the census the waves run against.

Two facts frame the decision:

1. **Terraform is the wrong tool for the census.** Terraform state
   describes resources *Terraform created*. It is authoritative for
   *new* VE provisioning (ADR 002 already scopes Terraform to config +
   `ve-instance` provisioning, explicitly not the upgrade/runtime flow).
   It is not, and should not become, a fleet inventory of pre-existing
   brownfield devices.

2. **A physical F5 and a VE-on-ESXi F5 are identical over the management
   API.** Both speak iControl REST; both have the two-volume boot design
   that NexusF5's rollback model depends on (see `docs/f5-primer.md`).
   The only difference is that a VE *also* appears in vCenter as a VM.

## Decision

Adopt **Nautobot** as the source-of-truth / discovery layer for the
existing fleet, populated by two feeders, and consumed by Ansible as a
**dynamic inventory** that replaces the static `hosts.yml`.

```
                    ┌─────────────────────────────┐
                    │          Nautobot           │   source of truth
                    │  devices, IPs, wave tags,    │
                    │  TMOS version, HA role,       │
                    │  active boot volume           │
                    └──────────▲────────▲───────────┘
                               │        │
        SSoT vSphere sync ─────┘        └───── Nautobot Job (scheduled)
        (is-it-a-VM, cluster,                   hits iControl REST per device:
         datastore, IP) — VE F5s only           sys/version, cm/failover-status,
                  ▲                              sys/software/volume
            ┌─────┴─────┐                       ┌────────▲─────────┐
            │  vCenter  │                       │ ALL F5s (phys+VE)│
            └───────────┘                       └──────────────────┘
                               │
                    ┌──────────┴───────────┐
                    │  Ansible dynamic      │  networktocode.nautobot.inventory
                    │  inventory (waves     │  → wave groups from Nautobot tags,
                    │  from Nautobot)       │     not hand-edited YAML
                    └───────────────────────┘
```

### The two feeders

1. **vCenter → Nautobot**, via the Nautobot **SSoT** (Single Source of
   Truth) framework's vSphere integration. Populates the VMware-side
   facts (the device is a VM, its cluster/datastore/IP) for the VE F5s.
   Physical F5s skip this feeder.

2. **iControl REST → Nautobot**, via a **Nautobot Job** — a scheduled
   Python task running inside Nautobot that polls each device's
   management API and writes TMOS version, HA role, and active boot
   volume into Nautobot custom fields. No off-the-shelf Nautobot F5
   integration exists, so this is the genuine new work — but it targets
   the *same* iControl REST endpoints the mock already simulates
   (`GET /mgmt/tm/sys/version`, `/mgmt/tm/cm/failover-status`,
   `/mgmt/tm/sys/software/volume`) and the ADR 007 brownfield tool
   already walks. It reuses competency the project has, against a
   surface the mock can already stand in for.

### Why Nautobot (vs. NetBox, vs. NAPALM-only)

- **Nautobot over NetBox:** Nautobot ships in-platform automation
  (**Jobs**), Git-backed config contexts, and the **SSoT** framework —
  so both feeders live *next to* the source of truth rather than as
  external glue. NetBox is leaner but would push the discovery jobs
  back out into separate cron/CI plumbing.
- **Not NAPALM/Nornir for the F5 facts:** F5 iControl REST is not a
  clean NAPALM driver. A purpose-built Nautobot Job hitting iControl
  REST is simpler and more honest than forcing F5 through a network-OS
  abstraction built for switches and routers.

### Consumption: dynamic inventory

Ansible consumes Nautobot via the first-party
`networktocode.nautobot.inventory` plugin. Wave membership
(`canary` / `wave_1` / …) becomes a Nautobot tag or dynamic group, not a
hand-edited YAML stanza. `hosts.yml` shrinks to (or is replaced by) an
inventory plugin config pointing at Nautobot; the waves run against live,
self-updating data. The static `hosts.yml` is retained only as the
mock-stack / offline test fixture.

## Scope (if/when built)

This ADR records a **direction**, not a committed build. If it proceeds,
the first cut is deliberately narrow:

- **In:** the iControl REST Nautobot Job (version / HA role / active
  volume); a Nautobot data model for an F5 device with wave-tag custom
  fields; the `networktocode.nautobot.inventory` wiring; a mock-backed
  test that proves the Job populates Nautobot from the existing mock
  endpoints and that the dynamic inventory yields the same wave groups
  the static `hosts.yml` does today.
- **Later / out of first cut:** the vCenter SSoT vSphere feeder (depends
  on a real or simulated vCenter — heavier to stand up than the mock);
  multi-vCenter / multi-site topology; write-back from Nautobot to F5;
  any UI/dashboard work beyond what Nautobot ships.

## Out of scope (explicit)

- **No VMware VM lifecycle management.** This is *discovery of F5 state*,
  not provisioning, placement, or guest-OS config of VMware VMs in
  general. NexusF5 stays an F5-upgrade-orchestration project; Nautobot
  enters only as the F5 fleet's source of truth. Broader VMware
  automation, if ever wanted, is a separate project — not a NexusF5
  scope expansion.
- **No replacing Terraform's provisioning role.** Terraform still owns
  new-VE provisioning and DO/AS3 declarations (ADR 002). Nautobot is the
  census of what *exists*; Terraform is how *new* things are made.
- **No Nautobot-as-config-author.** Declarative config remains
  Terraform-owned DO/AS3 (design principle 3). Nautobot holds inventory
  and runtime state, not the AS3/DO declarations themselves.
- **No real vCenter dependency in the test path.** Per the project's
  "everything testable without a real BIG-IP" principle, the first cut
  develops against the mock-f5 stack. The vCenter feeder, when built,
  gets its own simulation/fixture story rather than gating `make test`
  on a live vCenter.

## Consequences

- **`hosts.yml` changes role** from "the fleet census" to "the offline
  mock-stack fixture." Tests like `tests/test_wave_membership.py` need a
  story for both the static fixture and the Nautobot-derived inventory.
- **The mock grows a discovery customer.** The iControl REST Job reads
  the same endpoints the upgrade runbook does; mock fidelity work
  (ADR 006) already covers their shapes. Adding the Job should not
  demand new mock endpoints for the version/HA/volume facts.
- **New runtime dependency.** Nautobot is a Django app with a database;
  a portfolio reader now needs Nautobot stood up to see the discovery
  story. A `docker-compose` Nautobot service (mirroring the
  observability stack pattern) keeps this laptop-runnable.
- **The narrative tightens.** "Where does the inventory come from at
  fleet scale?" is currently unanswered (it's a YAML file). Nautobot
  answers it and composes with ADR 007: 007 discovers a device's
  *config*; this discovers the *fleet and its state*. Together they make
  "source of truth" honest for a brownfield estate.

## Related

- `docs/decisions/002-terraform-scope.md` — Terraform owns config +
  provisioning, not the runtime/upgrade flow. This ADR keeps the census
  out of Terraform for the same reason.
- `docs/decisions/007-brownfield-config-discovery.md` — sibling
  discovery concern (config, not inventory). Shares the iControl REST
  surface and the mock-first test discipline.
- `docs/decisions/006-mock-contract-fidelity.md` — the mock endpoints
  the discovery Job reads are already schema-pinned here.
- `docs/f5-primer.md` — TMOS, HA pairs, two-volume boot; why a physical
  F5 and a VE-on-ESXi F5 look identical over iControl REST.
- `ansible/inventory/hosts.yml` — the static census this direction
  replaces (and retains as a test fixture).
- Upstream: [Nautobot SSoT framework](https://docs.nautobot.com/projects/ssot/en/latest/),
  [Nautobot Jobs](https://docs.nautobot.com/projects/core/en/stable/development/jobs/),
  [`networktocode.nautobot` Ansible collection](https://nautobot-ansible.readthedocs.io/).

## Alternatives considered

- **Keep the static `hosts.yml` and stop.** Rejected as the long-term
  answer — it is a hand-maintained fiction that does not scale and does
  not reflect runtime state. Retained only as a test fixture.
- **NetBox instead of Nautobot.** Viable, leaner data model, but pushes
  the discovery jobs out into external plumbing. Nautobot's in-platform
  Jobs + SSoT keep discovery next to the source of truth. Chosen on the
  "automation lives near the data" axis.
- **Terraform as the inventory.** Rejected. Terraform state is a record
  of Terraform-created resources, not a brownfield fleet census;
  ADR 002 already draws this line.
- **NAPALM/Nornir for the F5 facts.** Rejected for the F5 polling path —
  F5 has no clean NAPALM driver; a direct iControl REST Job is simpler
  and reuses the mock surface.
