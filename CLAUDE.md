# CLAUDE.md — NexusF5

Context and conventions for working in this repository. Read before making changes.

## What this project is

NexusF5 automates F5 BIG-IP upgrades at fleet scale. It replaces the manual, engineer-per-device model with wave-based orchestration that drives hundreds of devices through patching, OS upgrades, and migrations in parallel, with automated health gates, approval checkpoints, and native rollback.

The project is both a working system (validated against a mock iControl REST server at scale, and real AWS BIG-IP VE HA pairs for end-to-end integration) and a portfolio artifact demonstrating orchestration, automation, and fleet-scale infrastructure upgrade patterns.

## Core design principles

1. **Hybrid-first, immutable-secondary.** The primary upgrade track is in-place on existing HA pairs using Ansible + iControl REST. The immutable (new-VE + cutover) track exists as a modernization example, not the default. Existing F5 estates don't get replaced — they get upgraded safely.

2. **Waves, not raw parallelism.** Upgrades flow through named waves (canary → wave 1 → wave 2 → wave 3) with human approval gates between waves and matrix parallelism within waves. This is the concept that turns months into days.

3. **Declarative config is source of truth.** Per-device DO (Declarative Onboarding) and AS3 (Application Services 3) declarations live in Terraform. Every upgrade ends with a declaration re-apply to confirm zero drift.

4. **Native rollback before orchestrated rollback.** BIG-IP's two-volume boot design handles almost all rollback scenarios. The orchestrator's job is to detect failure and flip the active volume, not to reconstruct state from scratch.

5. **Everything testable without a real BIG-IP.** The mock iControl REST server (`mock-f5/`) must let the full pipeline run end-to-end. `make test` runs against the mock; `make integration` runs against an AWS VE pair.

## Tech stack

| Layer | Tool | Notes |
|---|---|---|
| Declarative config | Terraform ≥ 1.9 | `F5Networks/bigip` provider for DO/AS3 |
| Upgrade runbook | Ansible ≥ 2.17 | `f5networks.f5_modules` + `f5networks.f5_bigip` collections |
| Orchestration | GitHub Actions | Environment gates, matrix strategy, reusable workflows |
| Mock F5 | Python 3.12 + FastAPI | Stateful iControl REST simulator |
| Modernization target | NGINX Plus (or OSS where reasonable) | BIG-IP LTM → NGINX cutover example |
| Observability | Prometheus + Grafana | Fleet upgrade dashboard |
| Linting | `ansible-lint`, `tflint`, `ruff`, `mypy`, `yamllint` | Enforced in PRs |

## Directory layout

```
nexusf5/
├── terraform/                    # DO/AS3 declarations, optional VE provisioning
│   ├── modules/
│   │   ├── do-declaration/
│   │   ├── as3-declaration/
│   │   └── ve-instance/          # AWS BIG-IP VE for integration + immutable track
│   ├── environments/
│   │   ├── lab/
│   │   ├── stage/
│   │   └── prod/
│   └── immutable-track/          # New-VE provisioning for modernization flow
├── ansible/                      # Upgrade runbook
│   ├── collections/requirements.yml
│   ├── inventory/
│   │   ├── group_vars/
│   │   │   ├── all.yml
│   │   │   ├── canary.yml
│   │   │   ├── wave_1.yml
│   │   │   ├── wave_2.yml
│   │   │   └── wave_3.yml
│   │   └── hosts.yml
│   ├── playbooks/
│   │   ├── upgrade.yml           # Main per-device upgrade playbook
│   │   ├── preflight.yml
│   │   ├── rollback.yml
│   │   └── validate.yml
│   └── roles/
│       ├── f5_preflight/         # HA state, sync, CPU/mem, connection count
│       ├── f5_backup/            # UCS backup to remote store
│       ├── f5_image_install/     # Image to inactive volume
│       ├── f5_boot_switch/       # Switch active volume + reboot
│       ├── f5_health_gate/       # Hard pass/fail gate after boot
│       ├── f5_failover/          # Traffic drain/failover helpers
│       └── f5_postcheck/         # DO/AS3 re-apply + drift check
├── .github/workflows/
│   ├── upgrade-canary.yml
│   ├── upgrade-wave.yml          # Reusable workflow, parameterized by wave
│   ├── rollback.yml
│   └── lint.yml
├── mock-f5/                      # FastAPI iControl REST simulator
│   ├── app/
│   │   ├── main.py
│   │   ├── endpoints/
│   │   ├── state.py              # Stateful device model (volumes, active, version)
│   │   └── chaos.py              # Optional failure injection
│   ├── tests/
│   └── Dockerfile
├── nginx/                        # BIG-IP LTM → NGINX Plus migration example
│   ├── source-bigip-config/
│   ├── target-nginx-config/
│   └── cutover-playbook/
├── observability/
│   ├── prometheus/
│   └── grafana/dashboards/
├── runbooks/                     # Operator-facing markdown referenced by playbooks
│   ├── 01-preflight-failure.md
│   ├── 02-image-install-stuck.md
│   ├── 03-post-boot-unhealthy.md
│   └── 04-rollback.md
├── docs/
│   └── decisions/                # ADRs — one file per decision
├── Makefile
├── CLAUDE.md
├── ARCHITECTURE.md
├── TODO.md
└── README.md
```

## Conventions

**Ansible**

- One role per discrete step. Roles are small, pure, and composable.
- Every task that calls iControl REST has a comment above it citing the F5 API endpoint (e.g. `# POST /mgmt/tm/sys/software/image`).
- Prefer `f5networks.f5_bigip` (the newer collection) over `f5networks.f5_modules` where both exist.
- No raw `ansible.builtin.uri` where a module exists. Raw `uri` is allowed only for endpoints the collections don't cover, and must be flagged with a `# raw-icontrol-rest` comment.
- Every task is tagged: `preflight`, `backup`, `install`, `reboot`, `postcheck`, `rollback`, `always`.
- `check_mode` must work for every role that can reasonably support it.
- Playbooks use `serial:` at the wave level, never at the host level within a playbook — GitHub Actions matrix handles intra-wave parallelism.

**Terraform**

- One workspace per environment. Never share state across environments.
- DO/AS3 declarations authored as HCL with `templatefile()`, rendered to JSON at apply. Don't check in generated JSON.
- Remote state via S3 + DynamoDB lock in `environments/*/backend.tf`.
- Every variable has a `description` and a `type`. Every module has a README.
- Use `moved` blocks for refactors, never `terraform state mv` inline.

**Python (mock-f5 and helpers)**

- Python 3.12. Typed. `ruff` + `mypy --strict` clean.
- FastAPI for the mock; Pydantic v2 models for every request and response.
- Pytest for tests; `httpx.AsyncClient` for integration tests against the mock.
- Async by default for endpoint handlers.

**GitHub Actions**

- Environments named `canary`, `wave-1`, `wave-2`, `wave-3`, each with required reviewers.
- Reusable workflows in `.github/workflows/_reusable/`.
- OIDC for AWS auth. No long-lived keys ever.
- Every job that touches a device publishes a structured JSON artifact (device, wave, start, end, status, error) that the Grafana dashboard consumes.
- Concurrency groups per wave to prevent overlapping runs.

## Non-negotiables

- **No real IPs, hostnames, or customer data.** RFC 1918 only. Device names follow `bigip-{site}-{number}` (e.g. `bigip-lab-01`, `bigip-dc1-042`).
- **No secrets in the repo.** `.env.example` only. Real values via GitHub Actions secrets or `sops`-encrypted files.
- **Idempotency is mandatory.** Every playbook is safely re-runnable. If a wave fails halfway, re-running must not damage devices that already completed.
- **Health gates are hard gates.** A failed post-upgrade check aborts the wave. No `ignore_errors: true` on health checks.
- **Rollback is a first-class playbook**, not an afterthought. `ansible-playbook playbooks/rollback.yml -l bigip-lab-01` must work standalone.
- **`make test` runs green on a laptop** with nothing but Docker, Python, Ansible, and Terraform installed. No real F5 required for the default test path.

## When you're unsure

- If a task seems to call for inventing an F5 API path, stop and verify against https://clouddocs.f5.com/api/icontrol-rest/ first.
- If a design choice could go either way (e.g. "should this be a role or a playbook?"), write a short ADR in `docs/decisions/NNN-title.md` using the [MADR](https://adr.github.io/madr/) format and pick one.
- If scope is creeping mid-phase, stop and flag it. Don't silently expand phase work.
- If a test is flaky, fix the test or fix the code — never mark it as skip.
- If a concrete literal from the plan feels over-specified, don't "tidy" it — the plan's verbosity is usually load-bearing. When you notice you're making something cleaner than the plan asked (e.g. sharding wave_1's 45 devices into 15/15/15 "for symmetry" instead of the 45 the plan specified), stop and ask instead of deciding.

## Where not to go

- No CMP (clustered multi-processing) edge cases — single HA pair per device in scope.
- No BIG-IQ integration — out of scope for v1.
- No AFM / ASM policy migration — LTM-focused.
- No actual tenant migration — config cutover example only.
- No vendor-specific hardware quirks (rSeries, VELOS) beyond noting they exist. Scope is TMOS on VE + generic hardware.

## Portfolio framing

This is a portfolio project, so the README and top-level docs are part of the deliverable. Treat docs as product, not afterthought. Every phase updates the relevant docs before the phase is considered done.
