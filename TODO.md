# TODO.md — NexusF5

Five phases. Work one at a time. Stop at the end of each phase for review.

At the end of every phase:
- All linters pass (`make lint`)
- All tests pass (`make test`)
- Relevant docs updated (README, ARCHITECTURE, runbooks)
- Phase Summary posted (see `KICKOFF_PROMPT.md`)

---

## Phase 1 — Foundation

**Goal:** Repo scaffolding, mock iControl REST server, and a working Ansible role that talks to the mock. Prove the testing loop before building the real runbook.

### Tasks

- [ ] Initialize repo with the directory structure from `CLAUDE.md`. Empty dirs get `.gitkeep`.
- [ ] `Makefile` with targets: `lint`, `test`, `integration`, `mock-up`, `mock-down`, `clean`.
- [ ] `.gitignore`, `.editorconfig`, `.pre-commit-config.yaml` with `ruff`, `ansible-lint`, `tflint`, `yamllint`, `mypy`.
- [ ] `mock-f5/` FastAPI app:
  - [ ] Pydantic v2 models for the iControl REST subset used by the runbook (version, volumes, ucs, failover-status, sync-status)
  - [ ] Stateful in-memory device model (see `ARCHITECTURE.md` → Mock iControl REST server)
  - [ ] Endpoints: `GET /mgmt/tm/sys/version`, `GET /mgmt/tm/cm/failover-status`, `GET /mgmt/tm/cm/sync-status`, `POST /mgmt/tm/sys/ucs`, `POST /mgmt/tm/sys/software/image`, `POST /mgmt/tm/sys/software/volume`, `POST /mgmt/tm/sys/failover`
  - [ ] `/health` and `/metrics` (Prometheus format)
  - [ ] Chaos endpoints under `/_chaos/` for failure injection
  - [ ] Dockerfile + `docker-compose.yml` that stands up 5 mock devices with distinct hostnames
  - [ ] Pytest suite covering happy path for every endpoint
- [ ] `ansible/roles/f5_preflight/` — pull version, HA state, sync state, performance stats. Set facts. Fail with a clear message if any check is red.
- [ ] `ansible/inventory/hosts.yml` with a `lab` group containing the 5 mock devices
- [ ] One-shot `playbooks/preflight.yml` that runs `f5_preflight` against the mock group
- [ ] `make test` runs the pytest suite *and* the preflight playbook against the mock, green end to end
- [ ] README: 30-second pitch at the top. Quickstart that gets a new dev from clone to green `make test` in under 5 minutes.

### Done when

`git clone && make mock-up && make test` runs green on a laptop with nothing but Docker, Python 3.12, and Ansible installed.

---

## Phase 2 — Hybrid upgrade runbook

**Goal:** Full per-device upgrade sequence working end-to-end against the mock. One playbook, composable roles, real rollback.

### Tasks

- [ ] `ansible/roles/f5_backup/` — UCS backup with remote destination (S3 or local fallback for tests)
- [ ] `ansible/roles/f5_image_install/` — download and install image to inactive volume. Poll install status with timeout + exponential backoff.
- [ ] `ansible/roles/f5_boot_switch/` — set inactive volume as active boot target, reboot, wait for iControl REST to respond.
- [ ] `ansible/roles/f5_health_gate/` — hard gate. Version check + service check + no critical alerts. No `ignore_errors`.
- [ ] `ansible/roles/f5_failover/` — drain and failover. Idempotent.
- [ ] `ansible/roles/f5_postcheck/` — validate version, run a "DO/AS3 drift check" stub (real check comes in Phase 4).
- [ ] `playbooks/upgrade.yml` — orchestrates the roles in sequence for a single device. Fully tagged.
- [ ] `playbooks/rollback.yml` — flip active volume back, reboot, health gate. Works standalone: `ansible-playbook playbooks/rollback.yml -l bigip-lab-01`.
- [ ] Extend mock server:
  - [ ] Realistic async timing for image install (configurable 30s default)
  - [ ] Reboot simulation (unreachable window, then returns at new version)
  - [ ] Chaos scenarios wired in: `fail-next-install`, `slow-reboot`, `post-boot-unhealthy`
- [ ] Integration test: `pytest tests/integration/test_upgrade_flow.py` that drives `playbooks/upgrade.yml` against a mock device, asserts new version, then runs rollback, asserts prior version
- [ ] Integration test for each chaos scenario — prove rollback works when upgrade fails mid-flight
- [ ] Write runbooks: `runbooks/01-preflight-failure.md`, `02-image-install-stuck.md`, `03-post-boot-unhealthy.md`, `04-rollback.md`. Each playbook role references the appropriate runbook in its failure messages.

### Done when

Upgrade a single mock device from 16.1.3 → 17.1.0 via `ansible-playbook playbooks/upgrade.yml -l bigip-lab-01`. Chaos-injected failures trigger rollback correctly. Every failure mode has a runbook. All green in `make test`.

---

## Phase 3 — Wave orchestration via GitHub Actions

**Goal:** Scale the runbook to the fleet. Waves, approvals, matrix parallelism, artifacts.

### Tasks

- [ ] Expand mock Compose stack to 50 devices (canary + wave 1: 5 + 45 — enough to prove the model)
- [ ] Extend inventory: `canary`, `wave_1`, `wave_2`, `wave_3` groups with `group_vars/*.yml` setting per-wave tuning (timeouts, parallelism hints)
- [ ] `.github/workflows/_upgrade-wave-reusable.yml` — reusable workflow (top-level only — GitHub Actions rejects subdirectories under `.github/workflows/`; `_` prefix + `on: workflow_call:`-only signals "not for direct dispatch"):
  - [ ] Inputs: `wave_name`, `parallelism`, `target_version`
  - [ ] Matrix strategy dynamically built from inventory
  - [ ] Publishes one JSON artifact per device (wave, device, start, end, status, error)
  - [ ] Concurrency group per wave
- [ ] `.github/workflows/upgrade-canary.yml` — serial, 5 devices, triggers on manual dispatch
- [ ] `.github/workflows/upgrade-wave.yml` — calls reusable workflow for wave 1/2/3. Requires environment approval. Wave N gated on Wave N-1 success rate.
- [ ] `.github/workflows/rollback.yml` — manual-dispatch, device-scoped rollback
- [ ] GitHub environments configured: `canary`, `wave-1`, `wave-2`, `wave-3`, each with required reviewers
- [ ] Artifact aggregator: small Python script in `observability/ingest/` that reads artifacts and pushes to Prometheus Pushgateway (local for dev, real Pushgateway for prod)
- [ ] Act-based local testing: `make test-actions` runs the canary workflow locally via `nektos/act` against the mock stack
- [ ] Document the wave rollout process in `runbooks/05-running-a-wave.md`

### Done when

Trigger `upgrade-canary.yml` manually → 5 mock devices upgrade serially → artifacts publish → manual approval gates wave 1 → 50 mock devices upgrade 10 at a time → Grafana dashboard (stubbed is fine, polished in Phase 5) shows the progression.

---

## Phase 4 — Terraform track + immutable path

**Goal:** Declarative config as source of truth, plus the secondary immutable-VE track for modernization.

### Tasks

- [x] `terraform/modules/do-declaration/` — renders a DO declaration from HCL vars via `templatefile()`, submits via `bigip_do` resource (PR 1)
- [x] `terraform/modules/as3-declaration/` — same pattern for AS3 via `bigip_as3` resource (PR 1)
- [x] `terraform/environments/lab/` — points at mock server (via the nginx adapter sidecar in `mock-f5/proxy/`, since the F5 provider has no path-prefix support) with 5 canary devices wired up (PR 1)
- [x] Real DO/AS3 drift check in `f5_postcheck` role: runs `terraform plan -detailed-exitcode`, fails if exit code indicates drift (PR 1)
- [ ] `terraform/modules/ve-instance/` — AWS BIG-IP VE provisioning (AMI lookup, VPC, subnets, security groups, IAM) (PR 2)
- [ ] `terraform/immutable-track/` — end-to-end immutable example: (PR 2)
  - [ ] Provisions a new VE at target version
  - [ ] Applies same DO/AS3 declarations (proves portability)
  - [ ] Outputs new VE endpoint for synthetic validation
- [ ] `ansible/playbooks/immutable-cutover.yml` — synthetic validation + DNS cutover stub + old-VE-drain (PR 2)
- [ ] Integration test: `make integration` spins up a real AWS VE pair (tagged `purpose=nexusf5-test`, `auto-destroy=true`), runs preflight + one-shot upgrade round-trip, tears down. Runs in GitHub Actions on `workflow_dispatch` only — not on PRs (cost control). (PR 2)
- [ ] **Pre-merge for PR 2:** drop `refs/heads/phase-4-aws-ve` from `trusted_branch_refs` in `terraform/environments/shared/variables.tf`, re-apply, verify trust policy via `test-aws-auth.yml` from `main`. A feature branch in the trust policy is permanent attack surface — branch can be re-created post-merge by anyone with write access and the policy still accepts it.
- [ ] ADR: `docs/decisions/003-hybrid-vs-immutable.md` explaining when each applies (PR 3 — renumbered from `001-hybrid-vs-immutable.md` because `001-mock-topology.md` already exists)
- [x] ADR: `docs/decisions/002-terraform-scope.md` on why Terraform owns config but not upgrade flow (PR 1)

### Done when

`cd terraform/environments/lab && terraform apply` configures the mock devices with DO/AS3. An upgrade run ends with zero Terraform drift. The immutable track provisions, configures, and cuts over a second mock instance. `make integration` runs a real AWS VE round-trip and returns clean.

---

## Phase 5 — NGINX modernization + observability + polish

**Goal:** NGINX track, real Grafana dashboards, portfolio-grade docs. Make the repo presentable.

### Tasks

- [ ] `nginx/source-bigip-config/` — representative BIG-IP LTM VIP (AS3 declaration): pool of 3 backends, TLS SNI, one iRule, persistence profile
- [ ] `nginx/target-nginx-config/` — equivalent NGINX Plus config. Document iRule equivalence with caveats (what maps cleanly, what doesn't, what's NGINX Plus-only vs OSS).
- [ ] `nginx/cutover-playbook/` — Ansible playbook:
  - [ ] Deploy NGINX config
  - [ ] Synthetic validation (curl checks against new endpoint)
  - [ ] Drain sessions on BIG-IP VIP via iControl REST
  - [ ] DNS cutover stub (comment where real provider integration would plug in)
  - [ ] BIG-IP VIP remains available as fallback for defined window
- [ ] ADR: `docs/decisions/003-when-to-modernize-to-nginx.md` — decision framework for which workloads are good candidates
- [ ] `observability/prometheus/prometheus.yml` — scrape config for mock `/metrics` and Pushgateway
- [ ] `observability/grafana/dashboards/fleet-upgrade.json` — real dashboard: stacked bar by wave/status, per-device timing histogram, failure heatmap, rollback timeline
- [ ] `docker-compose.observability.yml` — full stack up: mock(s) + Prometheus + Pushgateway + Grafana with dashboard pre-loaded
- [ ] `make demo` — end-to-end: stand up 50 mock devices, trigger canary + wave 1 locally via `act`, dashboard populated at http://localhost:3000
- [ ] README polish:
  - [ ] 30-second pitch at top
  - [ ] Architecture diagram (Mermaid) — two tracks, wave flow, components
  - [ ] Scale-math callout ("month → days" with the numbers)
  - [ ] Screenshots of Grafana dashboard mid-rollout
  - [ ] Tech stack badges
  - [ ] CI status badges for all four workflows (lint, ingest, python, ansible)
  - [ ] "What this demonstrates" section mapping capabilities (orchestration at scale, declarative config, automated rollback, modernization path) to concrete files in the repo
- [ ] Resolve pre-existing yamllint warning on `ansible/roles/f5_backup/tasks/main.yml:10` (line >140 chars; non-fatal, predates Phase 4 PR 1)
- [ ] Align mock iControl REST listen port with real F5 17.1.x default (8443 instead of 8080). Phase 4 PR 2 follow-up: real BIG-IP listens on 8443; mock listens on 8080 (HTTP, no TLS — different shape). Mismatch is currently fine because the lab terraform env routes via the proxy adapter using path-prefix, but a future test that exercises the integration wrapper against the mock would surface a "works against mock, fails against real F5" gap. Touches `mock-f5/Dockerfile` (EXPOSE + uvicorn --port), `mock-f5/docker-compose.yml` port mapping, `proxy/` adapter targets, and any healthcheck URLs.
- [ ] Final portfolio pass: every `TODO` comment in code addressed or documented, every role has a README, every workflow has a comment block explaining what triggers it

### Done when

`make demo` produces a running local system with a populated Grafana dashboard in under 10 minutes from a clean clone. The README sells the project in 30 seconds. Every capability claim in the README has a concrete repo pointer. The NGINX example cuts over a mock workload cleanly.

---

## Optional stretch

Only after all five phases are done and the repo is portfolio-polished.

- [ ] BIG-IQ integration path sketch (ADR only, no code)
- [ ] F5OS (rSeries) upgrade flow notes (ADR only)
- [ ] Blue/green at the GTM level for the immutable track
- [ ] Pull request that demonstrates a "bad image pulled by canary" incident end-to-end with runbook evidence
- [ ] Recorded demo video (<3 min) embedded in README
