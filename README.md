# NexusF5

> F5 BIG-IP fleet upgrades in **days, not months.** Wave-based orchestration,
> declarative config, automated rollback, and a mock iControl REST server that
> makes the entire pipeline testable on a laptop — no real F5 required.

NexusF5 replaces the manual, engineer-per-device upgrade model with orchestrated
waves (canary → wave 1 → wave 2 → wave 3) that drive hundreds of BIG-IP HA pairs
through patching, OS upgrades, and migrations in parallel, with automated health
gates, approval checkpoints, and native two-volume rollback.

## Why it matters

A 500-device F5 estate patched device-by-device is roughly 1,500 engineer-hours
of serial work — months end-to-end. By the time one upgrade cycle finishes, the
next is already overdue. NexusF5 compresses the full rollout into ~2 working
weeks with a handful of engineers monitoring. See
[`ARCHITECTURE.md`](ARCHITECTURE.md) for the scale math and the wave model.

## Quickstart

Prerequisites: Docker, Python 3.12, Ansible ≥ 2.17, and
[uv](https://github.com/astral-sh/uv).

```bash
git clone <this-repo>
cd nexusf5

# Install Python + Ansible collection dependencies
make install-deps

# Stand up the 50-device multiplexed mock fleet and run the test suite
make test
```

You should see pytest green, then the preflight playbook running against all
50 mock devices with every health assertion passing. The mock stays running
after `make test`; stop it with `make mock-down`.

One shared container at `http://localhost:8100` hosts every device; the
hostname is the first URL path segment (`/bigip-lab-01/mgmt/tm/sys/version`).
See [`docs/decisions/001-mock-topology.md`](docs/decisions/001-mock-topology.md)
for the routing rationale.

### Pre-push check

Two lint targets, two purposes:

```bash
make lint       # fast — uses host tooling; runs in seconds, for iteration
make lint-ci    # authoritative — runs the exact CI sequence inside a
                # python:3.12-slim container with the pinned uv version
                # and a fresh pip-installed ansible-lint. This is what to
                # run before pushing a PR.
```

The split exists because host tooling can drift silently from CI
(different uv, Debian-patched ansible-lint, stale caches) and `make lint`
can go green while CI stays red. `make lint-ci` closes that gap.

### Optional: local pre-commit hooks

CI enforces ruff, mypy, yamllint, and ansible-lint regardless. If you'd like
them to run on every local commit too:

```bash
pip install pre-commit
pre-commit install
```

## What's in the repo

| Path | Purpose |
|---|---|
| `mock-f5/` | FastAPI iControl REST simulator — stateful, chaos-injectable |
| `ansible/` | Per-device upgrade runbook (Phase 1: preflight role) |
| `terraform/` | DO/AS3 as source of truth; VE provisioning for the immutable track (Phase 4) |
| `.github/workflows/` | Wave orchestration: canary, wave 1/2/3, rollback (Phase 3) |
| `nginx/` | BIG-IP LTM → NGINX Plus modernization example (Phase 5) |
| `observability/` | Prometheus + Grafana fleet upgrade dashboard (Phase 5) |
| `runbooks/` | Operator-facing docs keyed off failure modes |
| `docs/decisions/` | ADRs (architectural decisions, one file each) |

## Development status

**Phase 4 in progress** (PR 1 of 3 merged). Phases 1–3 complete.
Phase 4 PR 1 introduces the Terraform DO/AS3 modules, a lab environment
wired to the canary mock devices via an nginx adapter sidecar (the F5
provider has no path-prefix support, so each device gets a dedicated
port at 8101–8105), and a real `terraform plan -detailed-exitcode`
drift gate in the `f5_postcheck` role. PR 2 adds the AWS BIG-IP VE
modules and the immutable track; PR 3 ships ADR 003. See
[`TODO.md`](TODO.md) for the full phase plan.

Run `make test-unit` for the fast dev loop (in-process, ~0.4s). Run
`make test` for the full suite including integration tests that drive
`upgrade.yml` / `rollback.yml` against the live mock stack (~6 minutes).

## Further reading

- [`CLAUDE.md`](CLAUDE.md) — conventions and non-negotiables
- [`ARCHITECTURE.md`](ARCHITECTURE.md) — problem context, two tracks, wave model,
  per-device sequence, rollback model
- [`docs/decisions/`](docs/decisions/) — ADRs
