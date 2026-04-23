# 01 — Preflight failure

An upgrade was aborted because a preflight assertion failed. This runbook is
referenced from failure messages in `ansible/roles/f5_preflight/tasks/main.yml`.

## Likely causes and first actions

| Assertion | Likely cause | First action |
|---|---|---|
| HA color `red` | Peer unreachable, sync broken, licence expired | `GET /mgmt/tm/cm/sync-status` on both peers; verify peer mgmt IP reachability |
| Sync status not `In Sync` | Config drift between peers, pending sync | Force a sync from the active peer: `tmsh run cm config-sync to-group <group>` |
| CPU over threshold | Load spike (synthetic or real) or runaway process | Wait 10 min and retry; if persistent, capture `top`/qkview |
| Memory over threshold | Memory leak or sustained high load | Capture qkview; escalate before retrying |
| Connection count over ceiling | Busy VIP, pre-maintenance traffic surge | Delay the wave; confirm maintenance window with the traffic owner |

## Do not

- **Re-run with `f5_preflight_fail_on_red=false` to "get past" the gate.**
  Preflight thresholds are a pre-change safety check; overriding them
  removes the safety.
- **Skip preflight.** Downstream roles set facts from `f5_preflight`; skipping
  it will break them.

## Before retrying

1. Re-run preflight against the single device:
   `ansible-playbook playbooks/preflight.yml -l bigip-lab-01`
2. Confirm the failing assertion now passes.
3. If a wave was mid-flight, re-dispatch the workflow on the same commit —
   idempotency guarantees already-upgraded devices are no-ops.

## Phase note

Phase 1 implements the role and this runbook. Phases 2–3 will reference the
same runbook when richer failure modes surface (image install stall, post-boot
timeout, etc. — see `runbooks/02-*` and `03-*` when written).
