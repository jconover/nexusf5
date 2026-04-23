# ADR 001 — Mock F5 topology: one container per device → multiplexed at scale

- Date: 2026-04-23
- Status: Accepted

## Context

The mock iControl REST server (`mock-f5/`) must let the full upgrade pipeline
run end-to-end without real BIG-IP hardware. Phase 1 needs 5 simulated devices
(`bigip-lab-01`..`bigip-lab-05`); Phase 3 scales to 50 (canary + wave 1); the
portfolio target is ~500 devices.

Two topologies were on the table:

1. **One container per device.** Each docker-compose service is a distinct
   mock instance bound to a distinct host port. Device hostname provided via
   the `MOCK_F5_HOSTNAME` environment variable. Inventory maps each device to
   a `localhost:PORT` endpoint.
2. **Multiplexed: one container hosting N devices.** A single mock process
   holds a `hostname -> DeviceState` map and routes requests by `Host` header
   (or path prefix).

## Decision

**Phase 1 uses topology (1).** One container per device, ports 8101–8105.

**Phase 3 migrates to topology (2).** A single container multiplexing many
devices, keyed by `Host` header.

The state layer (`mock-f5/app/state.py`) is written now to be multi-device
capable: `StateStore` holds a `dict[hostname, DeviceState]` and exposes
`register`, `get`, `all`, and `primary`. Phase 1 registers exactly one device
per container, but the contract of the state module does not change when
Phase 3 switches.

## Rationale

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
  `app/main.py`. State, models, and endpoint handlers do not change.

## Consequences

- **Phase 1 inventory** carries explicit per-device ports in
  `ansible/inventory/hosts.yml` (`f5_api_base_url: http://localhost:810X`).
- **Phase 3 inventory** will point every device at the same shared host/port
  and disambiguate via `Host` header (the F5 `provider.server` arg becomes
  a shared endpoint; a per-host `Host` override is added). No changes to the
  role's task bodies beyond the URL/header composition.
- **Chaos endpoints** already take a hostname in the URL
  (`/_chaos/{hostname}/...`), so they carry through Phase 3 unchanged.
- **`/metrics`** today exposes the single device in this container; in Phase
  3 it exposes every multiplexed device, labelled by hostname. The
  Prometheus scrape config will follow the same change.

## Follow-up (Phase 3 refactor checklist)

- [ ] Switch `app/main.py` from `build_store_from_env()` to
      `build_store_from_manifest()` (reads a JSON file listing devices).
- [ ] Change `get_device` in `app/deps.py` to look up by the `Host` header.
- [ ] Collapse `docker-compose.yml` to a single service exposing a single
      port; point inventory at it with per-device `Host` overrides.
- [ ] Expect zero changes in `app/state.py`, `app/models.py`, or
      `app/routers/*.py` — if any of those need to change, stop and
      reconsider whether the state model was kept abstraction-clean.
