# ADR 001 — Mock F5 topology: one container per device → multiplexed at scale

- Date: 2026-04-23 (Phase 3 amendment: 2026-04-24)
- Status: Accepted — amended in Phase 3 to pick path-prefix routing over Host-header

## Context

The mock iControl REST server (`mock-f5/`) must let the full upgrade pipeline
run end-to-end without real BIG-IP hardware. Phase 1 needs 5 simulated devices
(`bigip-lab-01`..`bigip-lab-05`); Phase 3 scales to 50 (canary + wave 1–3);
the portfolio target is ~500 devices.

Two topologies were on the table:

1. **One container per device.** Each docker-compose service is a distinct
   mock instance bound to a distinct host port. Device hostname provided via
   the `MOCK_F5_HOSTNAME` environment variable. Inventory maps each device to
   a `localhost:PORT` endpoint.
2. **Multiplexed: one container hosting N devices.** A single mock process
   holds a `hostname -> DeviceState` map and routes requests to the right
   device via one of:
   - **(2a) `Host:` header.** Closest analogue to the real F5 model where
     each device is a distinct HTTPS endpoint at its own DNS name.
   - **(2b) Hostname in the URL path.** Every iControl REST path is prefixed
     with the device hostname, e.g. `/bigip-lab-01/mgmt/tm/sys/version`.

## Decision

**Phase 1 uses topology (1).** One container per device, ports 8101–8105.

**Phase 3 migrates to topology (2b): a single container multiplexing many
devices, keyed by hostname as the first URL path segment.**

The state layer (`mock-f5/app/state.py`) is written to be multi-device
capable: `StateStore` holds a `dict[hostname, DeviceState]` and exposes
`register`, `get`, `all`, and `has`. Phase 1 registered exactly one device
per container; Phase 3 registers many devices from a JSON manifest.

Routing layer in Phase 3:

- iControl REST router prefix: `/{hostname}/mgmt/tm` (was `/mgmt/tm`).
- `get_device` dependency reads `request.path_params["hostname"]` and
  returns `store.get(hostname)`, raising 404 for unknown devices.
- Chaos endpoints were already scoped by path (`/_chaos/{hostname}/...`)
  and carry through unchanged.
- `/health` and `/metrics` remain at root — they report on every
  multiplexed device, labelled by hostname.

## Why path-prefix over Host header

Both options route the same information (which device is this request for?)
and cost the same at the routing layer. The tiebreaker is operator and
test-harness ergonomics. The Phase 3 pipeline is exercised locally via
`nektos/act`, from `curl` inside runbooks, and from `httpx` in the Python
integration suite. All three prefer path prefixes:

- **Debuggable with `curl` and browser DevTools.** No `-H 'Host: ...'`
  incantation required. Copy-paste a URL and it works.
- **Visible in every log line.** Uvicorn and every intermediate proxy log
  paths by default; hosts only with extra config. When a wave fails at
  3AM, greppable device identity in the access log is worth more than
  protocol realism.
- **No `act` / reverse-proxy surprises.** `nektos/act` runs jobs in
  containers, and some middleware rewrites or drops non-matching `Host`
  headers. Path-based routing sidesteps this entire category of bug.
- **No split-horizon DNS needed.** With Host-header routing, drivers either
  inject a header per request or the operator sets up
  `/etc/hosts`-style resolution. Path routing is `http://localhost:8100`
  for every device, disambiguated by the first path segment.

The cost is one cosmetic divergence from the real F5 API shape: real
BIG-IP endpoints start with `/mgmt/tm`, not `/{hostname}/mgmt/tm`. The
Ansible roles wrap the base URL in `f5_api_base_url`, so inventory flips
from `http://localhost:8101` to `http://localhost:8100/bigip-lab-01` and
every role URL template (`{{ f5_api_base_url }}/mgmt/tm/...`) continues
to work unchanged. Real-F5 integration (Phase 4) uses a DNS or VIP
per device, so the inventory's `f5_api_base_url` simply becomes
`https://bigip-dc1-042.example.net` and path-prefix routing is not
exercised — it only exists for the mock.

## Rationale for the split (unchanged)

- **Phase 1 realism.** One container per device mirrors a real F5 management
  plane (each device has its own endpoint, its own state, its own port).
  Easier to reason about during incident review and while the runbook is
  being built.
- **Phase 3 pragmatism.** 50 containers on a laptop is workable but wasteful;
  500 is not. A multiplexed container covers the scale-rehearsal story
  cleanly.
- **Refactor cost kept low by design.** Keeping the state model multi-device
  capable from day one means the Phase 3 refactor touches only the routing
  layer — `app/deps.py`'s `get_device` dependency and the store-builder in
  `app/main.py`, plus the router prefix. State, models, and endpoint
  handlers do not change.

## Consequences

- **Phase 1 inventory** carried explicit per-device ports in
  `ansible/inventory/hosts.yml` (`f5_api_base_url: http://localhost:810X`).
- **Phase 3 inventory** points every device at the same shared host/port and
  disambiguates via a hostname URL prefix:
  `f5_api_base_url: http://localhost:8100/{{ inventory_hostname }}`.
  No changes to role task bodies.
- **Chaos endpoints** already take a hostname in the URL
  (`/_chaos/{hostname}/...`), so they carry through Phase 3 unchanged.
- **`/metrics`** today exposes the single device in this container; in Phase
  3 it exposes every multiplexed device, labelled by hostname. The
  Prometheus scrape config will follow the same change.
- **Integration test helpers** (`mock-f5/tests/integration/helpers.py`)
  collapse `DEVICE_PORTS` to a single shared base URL and build per-device
  URLs with the hostname prefix.
- **Existing in-process unit tests** (`mock-f5/tests/test_*.py`) prepend
  `/bigip-lab-01` to every iControl REST path they hit; the `client`
  fixture still boots a single-device store, so those tests continue to
  exercise one device at a time.

## Phase 3 refactor checklist (status)

- [x] Switch `app/main.py` from `build_store_from_env()` to
      `build_store_from_manifest()` (reads a JSON file listing devices)
      with env-based fallback for the in-process test fixture.
- [x] Change `get_device` in `app/deps.py` to look up by the hostname path
      parameter.
- [x] Collapse `docker-compose.yml` to a single service exposing a single
      port; point inventory at it with per-device path prefixes.
- [x] Zero changes required in `app/state.py`, `app/models.py`, or
      `app/routers/*.py` handler bodies. Router prefix is the only delta.
