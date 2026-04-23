# ARCHITECTURE.md — NexusF5

## Problem context

NexusF5 targets the operational reality of large F5 BIG-IP estates:

- ~500 devices running customized F5 products
- Traditional upgrade takes 2–4 hours per device, leading to weeks or months for a full rollout
- By the time one upgrade cycle completes, the next is already overdue
- Manual upgrades require dozens of engineers doing device-by-device work
- Goal: transform migrations, patching, and OS upgrades from months into days without impacting performance

This is a common pattern across enterprises with mature F5 footprints — the devices are stable, but the upgrade cadence can't keep up with security patching and feature requirements.

## Solution in one paragraph

NexusF5 is a wave-based orchestration platform that drives F5 BIG-IP HA pairs through patching and OS upgrades in parallel. It owns config declaratively (Terraform → DO/AS3), executes the upgrade runbook via Ansible + iControl REST, and coordinates the fleet through GitHub Actions with environment-gated approvals and matrix parallelism. A mock iControl REST server lets the entire pipeline run end-to-end at hundreds-of-devices scale on a laptop, while AWS BIG-IP VE HA pairs validate the runbook against real F5 software. A secondary "immutable" track provisions new VEs at the target version and cuts traffic over — a modernization example for greenfield or migratable workloads.

## Two tracks

### Primary: Hybrid (in-place HA upgrade)

The realistic path for existing on-prem HA BIG-IP estates.

- **Terraform** owns DO (base system config) and AS3 (application delivery config) as declarative source of truth. Terraform does *not* drive the upgrade itself.
- **Ansible** owns the per-device upgrade runbook: preflight, backup, image install, volume switch, reboot, health gate, failover, postcheck.
- **GitHub Actions** owns fleet-level orchestration: waves, approvals, matrix parallelism, artifact publishing, rollback triggers.
- After each device upgrade, Terraform re-applies the DO/AS3 declarations to confirm zero drift against the source of truth.

### Secondary: Immutable (new-VE cutover)

The modernization example. Appropriate when the environment allows it — greenfield, cloud-first, or workloads that can tolerate a DNS/GTM cutover.

- Terraform provisions a new BIG-IP VE at the target TMOS version.
- Same DO/AS3 declarations applied to the new VE — proves declarations are portable.
- Synthetic validation (health checks against the new VIP) runs before cutover.
- GTM/DNS cutover drains the old VE; it stays up as a rollback target for a defined window, then gets destroyed.

Having both tracks in one repo is the strongest portfolio framing: it demonstrates understanding of *when* each pattern applies instead of picking one dogmatically.

## Wave orchestration model

The mechanism that turns months into days.

| Wave | Device count | Gate before | Parallelism within |
|---|---|---|---|
| Canary | 5 | Manual approval (release manager) | Serial — one at a time |
| Wave 1 | 45 | Manual approval + canary health dashboard review | Matrix of 10 concurrent |
| Wave 2 | 150 | Manual approval + wave 1 success rate ≥ 99% | Matrix of 20 concurrent |
| Wave 3 | 300 (remainder) | Manual approval + wave 2 success rate ≥ 99.5% | Matrix of 20 concurrent |

Wave membership is a property of inventory (Ansible group membership), not decided at runtime. A device is in exactly one wave. This makes the rollout reproducible, auditable, and easy to reason about during incident review.

**Why waves instead of just parallelism:** pure parallelism risks correlated failure across hundreds of devices at once. Waves bound blast radius, provide natural approval checkpoints that change management will sign off on, and surface systemic problems (bad image, bad config template) while the damage is contained to five devices rather than five hundred.

**Time math:**
- Manual today: 500 devices × 3 hours × 1 engineer = 1,500 engineer-hours, serial → months
- NexusF5: canary ~15h + wave 1 (45 / 10 concurrent = 5 batches × 3h = 15h) + wave 2 (150 / 20 = 8 batches × 3h = 24h) + wave 3 (300 / 20 = 15 batches × 3h = 45h) ≈ ~100 hours of pipeline time with approval gates ≈ ~2 working weeks end to end, 1–2 engineers monitoring. Months → days.

## Per-device upgrade sequence

Every device — canary or wave 3 — goes through the same sequence. The sequence is the contract.

```
┌─────────────────────────────────────────────────────────────┐
│                      PER-DEVICE UPGRADE                      │
└─────────────────────────────────────────────────────────────┘

  1. PREFLIGHT          → HA state, sync status, CPU/mem, open connections
                          GET  /mgmt/tm/cm/failover-status
                          GET  /mgmt/tm/cm/sync-status
                          GET  /mgmt/tm/sys/performance/all-stats

  2. BACKUP             → UCS to remote store (S3)
                          POST /mgmt/tm/sys/ucs

  3. IMAGE DOWNLOAD     → TMOS image to inactive volume
                          POST /mgmt/tm/sys/software/image

  4. IMAGE INSTALL      → Install to inactive volume
                          POST /mgmt/tm/sys/software/volume
                          (poll status until COMPLETE)

  5. BOOT SWITCH        → Set inactive volume as next boot
                          PATCH /mgmt/tm/sys/db/boot.quiet (prep)
                          POST  /mgmt/tm/sys/software/volume/{volume}

  6. REBOOT             → /mgmt/tm/sys save; reboot
                          POST /mgmt/tm/util/bash (or save + reboot via CLI)

  7. POST-BOOT WAIT     → Poll iControl REST until responsive
                          GET /mgmt/tm/sys/version

  8. HEALTH GATE        → Hard gate. Fail = stop and rollback.
                          Version match + services up + no critical alerts

  9. FAILOVER TRAFFIC   → Drain off peer, failover to this device
                          POST /mgmt/tm/sys/failover

 10. POSTCHECK          → DO/AS3 re-apply, drift = 0
                          Terraform apply (DO/AS3 modules)

 11. MARK GREEN         → Publish JSON artifact for Grafana
                          (wave, device, start, end, status, error)
```

Steps 3–10 repeat on the HA peer. The pair is green when both units are on the target version with zero drift and traffic has cycled through both.

## Rollback model

BIG-IP's two-volume boot design is the safety net. The orchestrator doesn't reconstruct state — it flips the active volume back and reboots.

**Rollback triggers:**
1. Health gate fails after reboot (step 8)
2. DO/AS3 re-apply shows unexpected drift (step 10)
3. Operator manually triggers the `rollback.yml` playbook

**Rollback sequence:**
```
  1. Set previous volume as active boot
     POST /mgmt/tm/sys/software/volume/{prior_volume}
  2. Reboot
  3. Health gate (same gate as upgrade)
  4. Restore UCS if drift detected (optional, operator-triggered)
     POST /mgmt/tm/sys/ucs with action=load
```

Rollback is tested in every phase — not a late-phase add-on.

## Mock iControl REST server

The piece that lets us validate the pipeline at scale without 500 real F5s.

**Implementation:** FastAPI app with in-memory state (SQLite-backed for persistence across test runs). Pydantic v2 models for every request and response. One endpoint handler per iControl REST path the runbook actually touches — implement the subset, not the whole API.

**Stateful device model:**
```python
class MockBigIP:
    hostname: str
    version: str
    ha_state: Literal["active", "standby"]
    sync_state: Literal["in-sync", "changes-pending", "disconnected"]
    volumes: list[Volume]          # [{name: "HD1.1", active: True, version: "17.1.0"},
                                   #  {name: "HD1.2", active: False, version: "16.1.3"}]
    connections: int
    cpu_pct: float
    in_progress_ops: list[Operation]  # simulates async image install
```

**Simulated async behavior:**
- `POST /mgmt/tm/sys/software/image` returns immediately; install completes after a configurable delay (default 30s for fast tests, 120s for realistic)
- Reboot simulated as a 60s window where the device is unreachable, then returns at the new version
- Failover state transitions happen with realistic latency

**Chaos injection:**
- `POST /_chaos/{device}/fail-next-install` — the next image install fails
- `POST /_chaos/{device}/slow-reboot` — reboot takes 10 minutes instead of 60 seconds
- `POST /_chaos/{device}/drift-postcheck` — postcheck finds config drift
- Used to validate rollback paths and wave-abort logic under failure.

**Scale:** one container instance can simulate 200+ devices with distinct hostnames and state. Docker Compose spins up 1 mock + 500 device records for full-fleet rehearsal.

## NGINX modernization track

F5 owns NGINX, and most realistic "F5 modernization" stories involve moving selected BIG-IP LTM VIPs to NGINX Plus — especially for microservices-adjacent workloads. This track demonstrates awareness of where the product line is heading and shows concrete hands-on experience with both halves of the F5 portfolio.

**Contents of `nginx/`:**

1. **Source config** — a representative BIG-IP LTM VIP with:
   - Pool of three backends with least-connections LB
   - TLS termination with SNI
   - One iRule (e.g. URI-based routing or header injection)
   - Persistence profile

2. **Target config** — equivalent NGINX Plus (or OSS where it works) config:
   - `upstream` block with matching LB method
   - `server` block with `ssl` directives
   - `map` or `if` for the iRule logic, with documented caveats
   - `sticky` for persistence (NGINX Plus only; note OSS fallback)

3. **Cutover playbook** — Ansible playbook that:
   - Deploys NGINX config
   - Runs synthetic validation
   - Drains sessions on the BIG-IP VIP via iControl REST
   - Updates DNS (example only — real DNS integration marked TODO)
   - Keeps BIG-IP VIP available as fallback for a defined window

4. **Decision doc** — `docs/decisions/0XX-when-to-modernize-to-nginx.md` — a short ADR-style piece on what workloads are good candidates and what isn't portable.

## Observability

Reuses the Prometheus + Grafana stack pattern from other NexusOps projects.

- **Metrics sources:**
  - F5 prometheus exporter (real devices, integration env)
  - Mock iControl REST server exposes `/metrics` directly
  - GitHub Actions job artifacts → a small ingestion script writes to Prometheus Pushgateway
- **Grafana dashboards:**
  - Fleet Upgrade Progress — stacked bar of devices by wave and status
  - Wave Timing — histogram of per-device upgrade duration, filterable by wave
  - Failure Heatmap — failure rate by device, site, version target
  - Rollback Log — timeline of rollback events

## Failure modes and how we handle them

| Failure | Detection | Response |
|---|---|---|
| Image install never completes | Timeout on install status poll (15 min) | Role fails. Playbook fails. Wave aborts. Rollback playbook available. |
| Reboot doesn't come back | Post-boot wait timeout (10 min) | Same. Peer remains active. Operator rollback. |
| Post-boot version mismatch | Health gate | Auto-rollback via native volume switch, then alert. |
| DO/AS3 drift post-upgrade | Terraform plan shows diff in postcheck | Wave pauses. Operator investigates. Rollback if drift is unexplained. |
| HA peer fails during upgrade | Preflight on peer (before touching it) | Wave aborts for that pair. Device that's already done stays done. |
| Bad target image (discovered in canary) | Canary health rate < 100% | Canary blocks wave 1 approval. Operator pulls the image. |

## Scale characteristics

- **Mock server** validates pipeline logic against 500 simulated devices.
- **AWS VE pair** validates the runbook against real TMOS behavior (1 pair, ~$5–10 per test run, torn down after).
- **GitHub Actions concurrency**: waves cap at 20 concurrent jobs. The F5 management plane on real hardware can take a beating from too many concurrent iControl REST sessions — 20 is a deliberate conservative ceiling, tunable per wave in `group_vars`.

## What this project is not

- Not a replacement for change management. It *feeds* change management (structured artifacts, clear gates) but doesn't replace sign-off.
- Not a policy migration tool. AFM/ASM rules are out of scope.
- Not an F5 reinvention. It orchestrates F5's own upgrade primitives (two-volume boot, iControl REST, DO/AS3) — the innovation is the orchestration wrapper, not the F5 internals.

## Key references

- iControl REST API: https://clouddocs.f5.com/api/icontrol-rest/
- Declarative Onboarding (DO): https://clouddocs.f5.com/products/extensions/f5-declarative-onboarding/latest/
- Application Services 3 (AS3): https://clouddocs.f5.com/products/extensions/f5-appsvcs-extension/latest/
- F5 Ansible Collection: https://clouddocs.f5.com/products/orchestration/ansible/devel/
- F5 Terraform Provider: https://registry.terraform.io/providers/F5Networks/bigip/latest/docs
