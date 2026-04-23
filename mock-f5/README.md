# mock-f5

Stateful mock iControl REST server for NexusF5 end-to-end tests and local
demos. Implements the subset of endpoints the upgrade runbook touches — not
the full API.

## Run

```bash
# One-off local run
cd mock-f5
uv sync
MOCK_F5_HOSTNAME=bigip-lab-01 uv run uvicorn app.main:app --port 8101

# Or bring up the full 5-device fleet via docker compose
make mock-up      # from repo root
```

## Endpoints

iControl REST (mirror real F5 paths):

- `GET /mgmt/tm/sys/version`
- `GET /mgmt/tm/cm/failover-status`
- `GET /mgmt/tm/cm/sync-status`
- `GET /mgmt/tm/sys/performance/all-stats`
- `POST /mgmt/tm/sys/ucs`
- `POST /mgmt/tm/sys/software/image`
- `POST /mgmt/tm/sys/software/volume`
- `POST /mgmt/tm/sys/failover`

Operational:

- `GET /health` — liveness + list of devices in this instance
- `GET /metrics` — Prometheus exposition format

Chaos (scope already hostname-keyed so Phase 3 multiplexing is a drop-in):

- `POST /_chaos/{hostname}/fail-next-install`
- `POST /_chaos/{hostname}/slow-reboot`
- `POST /_chaos/{hostname}/drift-postcheck`
- `POST /_chaos/{hostname}/post-boot-unhealthy`
- `POST /_chaos/{hostname}/reset`

## Topology

Phase 1 runs **one container per device** (ports 8101–8105). Phase 3 will
multiplex many devices into a single container, keyed by `Host` header. The
state module is already multi-device capable; only the routing layer
(`app/deps.py`, `app/main.py`) changes in Phase 3. See
[`docs/decisions/001-mock-topology.md`](../docs/decisions/001-mock-topology.md).

## Tests

```bash
cd mock-f5
uv run pytest -q
```

Tests use FastAPI's `TestClient` and run entirely in-process — no Docker
required for the pytest suite. The Ansible preflight playbook (invoked by
`make test`) is what exercises the containerised stack.
