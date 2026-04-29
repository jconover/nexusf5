# ADR 002 — Terraform owns DO/AS3 config; Ansible owns the upgrade flow

- Date: 2026-04-27
- Status: Accepted

## Context

Phase 4 introduces Terraform into a project that already has a working
Ansible-based per-device upgrade runbook. There is a real question of which
tool owns which surface, because both can technically drive the F5 control
plane and the team is small enough that a clean split saves more time than
a shared "everything in Ansible" or "everything in Terraform" approach
would.

This ADR is numbered 002 because `001-mock-topology.md` already exists. The
original `TODO.md` plan numbered this `002-terraform-scope.md`; the parallel
hybrid-vs-immutable ADR (originally planned as `001-hybrid-vs-immutable.md`)
will land as `003-hybrid-vs-immutable.md` in PR 3 to preserve append-only
ADR numbering.

The two surfaces in scope:

1. **Per-device configuration.** DO (declarative onboarding: hostname, DNS,
   NTP, VLANs, routes, the static plumbing of the management plane) and
   AS3 (application services 3: virtual servers, pools, monitors, iRules
   — the runtime config a tenant cares about).
2. **The upgrade flow.** Preflight checks, UCS backup, image install on the
   inactive volume, volume swap, reboot, post-boot health gate, failover
   re-balance, postcheck.

## Decision

**Terraform owns surface 1. Ansible owns surface 2. They meet at one
explicit hand-off: the Ansible postcheck role runs `terraform plan
-detailed-exitcode` as the drift gate.**

The split is structural, not opportunistic. The two surfaces have
fundamentally different state models, and forcing one tool to own both
makes the wrong tradeoffs in both directions.

## Decision framework

### Why DO/AS3 belongs in Terraform

DO and AS3 declarations are idempotent config blobs with a "current state →
desired state" model. Apply twice, get the same result. Drift is detectable
by re-reading the live declaration and diffing. This is the exact shape
Terraform was built for:

- **Plan/apply gives you a dry-run for free.** Reviewing a config change
  becomes a PR with a `terraform plan` artifact attached.
- **Drift detection is a side effect of `plan`.** No bespoke "compare live
  to expected" code; `plan -detailed-exitcode` exit code 2 is the signal.
- **State file is small and operationally inert.** DO/AS3 declarations are
  the kind of thing you want under version control, with PR review, and
  with a refusable plan before changes hit a device.
- **The provider is already there.** `F5Networks/bigip` has `bigip_do` and
  `bigip_as3` resources that handle the async task contract with the device.

Trying to do this in Ansible would mean writing the diff logic by hand,
storing prior state somewhere ad hoc, and losing PR-time previews.

### Why the upgrade flow belongs in Ansible

The upgrade flow is a **stateful sequence of imperative steps** with hard
gates and a rollback playbook. It is the opposite of "converge to desired
state":

- **The desired end state alone does not capture the upgrade.** "Be at
  17.1.0" is the goal, but the path through it (preflight → backup →
  install → reboot → health gate) has steps that must run in order, with
  gates that abort the rest if they fail. Terraform's "plan determines
  what to do, then do it" model assumes the operations are commutative and
  retryable; reboot is neither.
- **Failure semantics are different.** If a reboot fails mid-flight,
  Terraform's mental model — "you got an error, run apply again until it
  converges" — is dangerous. The right answer is "fail loudly, page an
  operator, run the rollback playbook." Ansible's `failed_when` + tagged
  rollback playbook is built for exactly this.
- **Health gates are first-class.** A post-reboot health check that fails
  must abort the wave before more devices are touched. Terraform has no
  natural seam for "stop the world, hand off to a different tool"; Ansible
  does.
- **Ordering, parallelism, and per-device fan-out are first-class.** Wave
  serialization (`serial:`), per-host failure isolation, and per-host
  variables are exactly what Ansible roles model well.

Trying to do this in Terraform would either mean modelling each device as
a `null_resource` with `local-exec` provisioners (giving up most of the
value of Terraform) or building a Terraform-driven state machine that
duplicates what Ansible already provides.

### Where they meet

The hand-off is one task in `f5_postcheck`:

```
terraform plan -detailed-exitcode -refresh=true
```

Exit 0 → drift gate passes → wave continues. Exit 1 or 2 → fail loud,
runbook 06 has the recovery procedure.

That's the entire shared surface. The Ansible flow does not call
`terraform apply`; the Terraform flow does not invoke Ansible playbooks.
Drift, when detected, is resolved by an operator (re-apply terraform,
re-run postcheck) — not by an automatic `apply` from the wave runner,
which could stomp on devices currently mid-upgrade.

## Consequences

- **Two source-of-truth systems.** DO/AS3 declarations live in
  `terraform/`. Upgrade orchestration lives in `ansible/`. Nothing else
  generates either.
- **Provider hosts the async contract.** Both `bigip_do` and `bigip_as3`
  carry strict expectations about the device's HTTP responses (task IDs,
  HTTP status codes, JSON shapes). The mock encodes those exactly; see
  `mock-f5/app/routers/extensions.py` for the contract.
- **Drift handling is human-in-the-loop, not automatic.** The wave fails
  on drift; an operator decides whether to re-apply terraform or
  investigate root cause. This is intentional — auto-applying terraform
  during a wave would mask real failures.
- **Operators learn one tool per surface.** Config changes go through
  Terraform PRs; upgrades through Ansible playbooks. Newcomers don't have
  to learn how the project bridges the two unless they're working on
  postcheck or the immutable track.

## Alternatives considered

- **Everything in Ansible.** Considered briefly; rejected because writing
  drift detection by hand and losing `plan` previews would cost more than
  introducing Terraform.
- **Everything in Terraform** (with `null_resource` provisioners for the
  upgrade steps). Rejected because Terraform's "converge to desired state
  with retries" model is actively wrong for sequenced reboot-and-gate
  operations. The failure mode (Terraform deciding to retry an interrupted
  reboot) is dangerous enough to disqualify the approach.
- **Split by environment** (Terraform for new environments, Ansible for
  existing). Rejected because it cuts orthogonally to the surface split:
  every environment has both surfaces and both tools, regardless of age.

## Related

- `docs/decisions/001-mock-topology.md` — how the mock multiplex routes
  `/{hostname}/...` requests
- `runbooks/06-postcheck-drift.md` — operator procedure when the drift
  gate fires
- `terraform/environments/lab/README.md` — apply workflow against the mock
