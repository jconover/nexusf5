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

Chaos (hostname-scoped):

- `POST /_chaos/{hostname}/fail-next-install`
- `POST /_chaos/{hostname}/slow-reboot`
- `POST /_chaos/{hostname}/drift-postcheck`
- `POST /_chaos/{hostname}/post-boot-unhealthy`
- `POST /_chaos/{hostname}/reset`
- `POST /_chaos/{hostname}/reset-device`

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
