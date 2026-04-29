# mock-f5

Stateful mock iControl REST server for NexusF5 end-to-end tests and local
demos. Implements the subset of endpoints the upgrade runbook touches — not
the full API.

## Run

```bash
# One-off local run (single device from env, defaults to bigip-lab-01)
cd mock-f5
uv sync
uv run uvicorn app.main:app --port 8100

# Or bring up the 50-device multiplexed stack via docker compose
make mock-up      # from repo root — binds :8100, reads manifests/lab-50.json
```

## Endpoints

iControl REST (mirror real F5 paths, prefixed with the device hostname):

- `GET  /{hostname}/mgmt/tm/sys/version`
- `GET  /{hostname}/mgmt/tm/cm/failover-status`
- `GET  /{hostname}/mgmt/tm/cm/sync-status`
- `GET  /{hostname}/mgmt/tm/sys/performance/all-stats`
- `POST /{hostname}/mgmt/tm/sys/ucs`
- `POST /{hostname}/mgmt/tm/sys/software/image`
- `POST /{hostname}/mgmt/tm/sys/software/volume`
- `POST /{hostname}/mgmt/tm/sys/failover`

Operational (root-scoped — report on the whole multiplex):

- `GET /health` — liveness + list of all devices this container serves
- `GET /metrics` — Prometheus exposition format, labelled by hostname

DO and AS3 (Phase 4 — F5 provider's `bigip_do` / `bigip_as3` async contract):

- `POST /{hostname}/mgmt/shared/declarative-onboarding` — submit DO declaration; returns 202 + task `id`
- `GET  /{hostname}/mgmt/shared/declarative-onboarding/task/{id}` — poll: 202+RUNNING, 200+OK, or 202+ERROR
- `GET  /{hostname}/mgmt/shared/declarative-onboarding` — last applied declaration (204 if none)
- `POST /{hostname}/mgmt/shared/appsvcs/declare/{tenant}` — submit AS3 declaration; returns 202 + task `id`
- `GET  /{hostname}/mgmt/shared/appsvcs/task/{id}` — poll: HTTP 200, status carried in `results[0].code` (0=running, 200=OK, 422=fail)
- `GET  /{hostname}/mgmt/shared/appsvcs/declare/{tenant}` — last applied declaration for tenant (404 if none)

Chaos (hostname-scoped):

- `POST /_chaos/{hostname}/fail-next-install`
- `POST /_chaos/{hostname}/slow-reboot`
- `POST /_chaos/{hostname}/drift-postcheck`
- `POST /_chaos/{hostname}/post-boot-unhealthy`
- `POST /_chaos/{hostname}/fail-next-do`
- `POST /_chaos/{hostname}/fail-next-as3`
- `POST /_chaos/{hostname}/reset`
- `POST /_chaos/{hostname}/reset-device`

## Proxy adapter sidecar

The F5 Terraform provider treats `address` as a bare host with no path-prefix
support, so it cannot reach the multiplexed mock directly. The `proxy/`
directory builds an nginx sidecar that listens on a dedicated port per
canary device (8101–8105), rewrites `/mgmt/...` to `/<hostname>/mgmt/...`,
and proxies to `mock-f5:8080`. See
[`proxy/README.md`](proxy/README.md) for the routing rationale and the
provider source-code references that motivate it.

## Topology

**Phase 3: one container multiplexing many devices**, keyed by the first
URL path segment (`/{hostname}/mgmt/tm/...`). Boot reads device list from
`MOCK_F5_MANIFEST` (JSON, falls back to `MOCK_F5_HOSTNAME` env for a
single-device dev run). ADR-001 explains why path-prefix routing beats
Host-header routing here: see
[`docs/decisions/001-mock-topology.md`](../docs/decisions/001-mock-topology.md).

Phase 1 history: originally one container per device on ports 8101–8105.
Kept in the ADR for context; no longer reflected in compose or inventory.

## Tests

```bash
cd mock-f5
uv run pytest -q
```

Tests use FastAPI's `TestClient` and run entirely in-process — no Docker
required for the pytest suite. The Ansible preflight playbook (invoked by
`make test`) is what exercises the containerised stack.
