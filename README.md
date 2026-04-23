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

# Stand up the 5-device mock fleet and run the Phase 1 test suite
make test
```

You should see pytest green, then the preflight playbook running against all
five mock devices with every health assertion passing. The mock stays running
after `make test`; stop it with `make mock-down`.

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

**Phase 1 of 5 complete.** The mock fleet + preflight role run green end-to-end.
See [`TODO.md`](TODO.md) for the full phase plan.

## Further reading

- [`CLAUDE.md`](CLAUDE.md) — conventions and non-negotiables
- [`ARCHITECTURE.md`](ARCHITECTURE.md) — problem context, two tracks, wave model,
  per-device sequence, rollback model
- [`docs/decisions/`](docs/decisions/) — ADRs
